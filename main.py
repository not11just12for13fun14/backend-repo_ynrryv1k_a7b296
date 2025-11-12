import os
import math
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="FlareChef API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Models ----------
class GenerateRequest(BaseModel):
    ingredients: str = Field(..., min_length=2, description="Comma-separated ingredients list")

class NutritionModel(BaseModel):
    calories: int
    protein: float
    carbs: float
    fat: float

class RecipeModel(BaseModel):
    title: str
    description: str
    ingredients: List[str]
    steps: List[str]
    time_minutes: int
    nutrition: NutritionModel
    image_url: Optional[str] = None

class SaveRecipeRequest(RecipeModel):
    pass

class RecipeInDB(RecipeModel):
    id: str
    created_at: Optional[str] = None


# ---------- Utilities ----------
CALORIE_HINTS = {
    "chicken": (165, 31, 0, 3.6),
    "beef": (250, 26, 0, 15),
    "pork": (242, 27, 0, 14),
    "salmon": (208, 20, 0, 13),
    "egg": (78, 6, 0.6, 5),
    "rice": (206, 4.3, 45, 0.4),
    "pasta": (221, 8, 43, 1.3),
    "potato": (161, 4.3, 37, 0.2),
    "beans": (155, 10, 28, 0.5),
    "tofu": (144, 17, 3, 9),
    "cheese": (113, 7, 0.4, 9.3),
    "milk": (103, 8, 12, 2.4),
    "olive oil": (119, 0, 0, 13.5),
    "butter": (102, 0.1, 0, 11.5),
    "bread": (79, 3, 15, 1),
    "avocado": (160, 2, 9, 15),
}

FALLBACK_IMAGE = "https://images.unsplash.com/photo-1504674900247-0877df9cc836?q=80&w=1600&auto=format&fit=crop"


def estimate_nutrition(ings: List[str]) -> NutritionModel:
    total_cals = total_pro = total_carb = total_fat = 0.0
    for raw in ings:
        k = raw.strip().lower()
        found = None
        for key in CALORIE_HINTS:
            if key in k:
                found = key
                break
        if found:
            c, p, cb, f = CALORIE_HINTS[found]
            total_cals += c
            total_pro += p
            total_carb += cb
            total_fat += f
        else:
            total_cals += 40
            total_carb += 5
    return NutritionModel(
        calories=int(total_cals),
        protein=round(total_pro, 1),
        carbs=round(total_carb, 1),
        fat=round(total_fat, 1),
    )


def craft_title(ings: List[str]) -> str:
    core = [i.strip().title() for i in ings if i.strip()]
    if not core:
        return "FlareChef Creation"
    if len(core) == 1:
        return f"Ignited {core[0]} Delight"
    return f"Flame-Kissed {' & '.join(core[:2])}{' Medley' if len(core)>2 else ''}"


def craft_description(ings: List[str]) -> str:
    base = ", ".join([i.strip() for i in ings if i.strip()])
    return f"A warm, glowing recipe that turns {base} into a cozy, restaurant-worthy dish."


def craft_steps(ings: List[str]) -> List[str]:
    lead = ings[0].strip().lower() if ings else "ingredients"
    return [
        "Preheat a skillet until it softly shimmers like a flame.",
        f"Add {lead} with a drizzle of oil; sear until lightly caramelized.",
        "Fold in remaining ingredients and season with salt, pepper, and a hint of heat.",
        "Simmer until flavors meld and textures are tender.",
        "Finish with fresh herbs or citrus and serve warm."
    ]


def compute_time(ings: List[str]) -> int:
    base = 10 + 5 * len(ings)
    return min(max(base, 15), 75)


# ---------- Routes ----------
@app.get("/")
def read_root():
    return {"message": "FlareChef API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


@app.post("/api/generate", response_model=RecipeModel)
def generate_recipe(payload: GenerateRequest):
    ingredients = [i.strip() for i in payload.ingredients.split(',') if i.strip()]
    if not ingredients:
        raise HTTPException(status_code=400, detail="Please provide at least one ingredient.")

    title = craft_title(ingredients)
    description = craft_description(ingredients)
    steps = craft_steps(ingredients)
    time_minutes = compute_time(ingredients)
    nutrition = estimate_nutrition(ingredients)

    # Simple image sourcing using Unsplash query
    query = "+".join(ingredients[:3]) or "food"
    image_url = f"https://source.unsplash.com/featured/?{query}"

    return RecipeModel(
        title=title,
        description=description,
        ingredients=ingredients,
        steps=steps,
        time_minutes=time_minutes,
        nutrition=nutrition,
        image_url=image_url or FALLBACK_IMAGE,
    )


@app.post("/api/recipes", response_model=dict)
def save_recipe(payload: SaveRecipeRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = payload.model_dump()
    inserted_id = create_document("recipe", doc)
    return {"id": inserted_id, "status": "saved"}


@app.get("/api/recipes", response_model=List[RecipeInDB])
def list_recipes(limit: int = 20):
    if db is None:
        return []
    docs = get_documents("recipe", limit=limit)
    results: List[RecipeInDB] = []
    for d in docs[::-1]:
        rid = str(d.get("_id"))
        created = d.get("created_at")
        created_str = None
        if created:
            try:
                created_str = created.isoformat()
            except Exception:
                created_str = str(created)
        results.append(RecipeInDB(
            id=rid,
            title=d.get("title", "Recipe"),
            description=d.get("description", ""),
            ingredients=d.get("ingredients", []),
            steps=d.get("steps", []),
            time_minutes=int(d.get("time_minutes", 20)),
            nutrition=NutritionModel(**d.get("nutrition", {"calories":0,"protein":0,"carbs":0,"fat":0})),
            image_url=d.get("image_url"),
            created_at=created_str,
        ))
    return results


@app.get("/api/recipes/{recipe_id}", response_model=RecipeInDB)
def get_recipe(recipe_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        obj_id = ObjectId(recipe_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid recipe id")
    doc = db["recipe"].find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Recipe not found")
    created = doc.get("created_at")
    created_str = created.isoformat() if hasattr(created, 'isoformat') else str(created)
    return RecipeInDB(
        id=str(doc.get("_id")),
        title=doc.get("title", "Recipe"),
        description=doc.get("description", ""),
        ingredients=doc.get("ingredients", []),
        steps=doc.get("steps", []),
        time_minutes=int(doc.get("time_minutes", 20)),
        nutrition=NutritionModel(**doc.get("nutrition", {"calories":0,"protein":0,"carbs":0,"fat":0})),
        image_url=doc.get("image_url"),
        created_at=created_str,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
