from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, status
from celery_app.tasks import process_pdf_task, delete_book_task
from database.auth import get_current_user
import os
import uuid
import shutil
from celery_app.celery_app import celery_app
from celery.result import AsyncResult
router = APIRouter(prefix="/pdf", tags=["PDF Upload & Delete"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# -------------------- Upload Route -------------------- #
@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a PDF, associate it with the authenticated user, 
    and trigger background processing via Celery.
    """
    try:
        # Save file temporarily
        file_id = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        user_id = str(current_user["id"])
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

        # Enqueue Celery background task with user_id
        task = process_pdf_task.delay(pdf_path=file_path, user_id=user_id)

        return {
            "message": "✅ File uploaded successfully. Processing started.",
            "task_id": task.id,
            "filename": file.filename,
            "uploaded_by": user_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")


# -------------------- Delete Route -------------------- #
@router.delete("/{book_id}")
async def delete_pdf(book_id: str, current_user: dict = Depends(get_current_user)):
    """
    Delete a book uploaded by the current user.
    - If the book is shared with other users → removes only the current user.
    - If the user is the only uploader → deletes from Mongo, Qdrant, and B2.
    """
    try:
        user_id = str(current_user["id"])
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

        # Enqueue Celery deletion task
        task = delete_book_task.delay(book_id=book_id, user_id=user_id)

        return {
            "message": "🧹 Deletion task started.",
            "task_id": task.id,
            "book_id": book_id,
            "requested_by": user_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Book deletion failed: {e}")


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """
    Check the current status or result of a Celery task.
    """
    task_result = AsyncResult(task_id, app=celery_app)
    
    return {
        "task_id": task_id,
        "status": task_result.status,       # e.g. PENDING, STARTED, SUCCESS, FAILURE
        "result": task_result.result if task_result.successful() else None,
    }