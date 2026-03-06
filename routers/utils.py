from fastapi import APIRouter
import os

router = APIRouter()

@router.get("/api/utils/file/exists")
async def check_file_exists(path: str):
    exists = os.path.exists(path)
    return {"exists": exists, "path": path}
