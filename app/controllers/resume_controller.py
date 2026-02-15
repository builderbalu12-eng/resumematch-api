from fastapi import HTTPException, status
from app.services.mongo import mongo
from app.models.resume.template import TemplateCreate, TemplateOut
from app.models.resume.schema import ResumeSchemaCreate, ResumeSchemaOut
from app.models.resume.user_resume import UserResumeCreate, UserResumeOut
from app.services.resume_generator import ResumeGenerator
from bson import ObjectId
from datetime import datetime
from typing import Any, Dict, Optional, List  # ← ADD THIS LINE
from app.config import settings   # ← ADD THIS LINE

class ResumeController:

    @staticmethod
    async def _is_admin(user_id: str) -> bool:
        try:
            user = await mongo.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return False
            
            user_email = user.get("email", "").strip().lower()
            
            # Use the settings property (set of lowercase emails)
            return user_email in settings.resume_admin_emails
            
        except Exception as e:
            print(f"Admin check failed for user {user_id}: {str(e)}")
            return False

    @staticmethod
    async def create_template(template_data: TemplateCreate, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(status_code=403, detail="Admin access required")

        collection = mongo.resume_templates
        
        existing = await collection.find_one({"template_id": template_data.template_id})
        if existing:
            raise HTTPException(400, "Template ID already exists")
        
        now = datetime.utcnow()
        doc = template_data.model_dump()
        doc.update({
            "_id": template_data.template_id,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "is_active": True
        })
        
        await collection.insert_one(doc)
        
        return {
            "status": 201,
            "success": True,
            "message": "Template created successfully",
            "data": TemplateOut(**doc).model_dump(by_alias=True)
        }

    @staticmethod
    async def list_templates(
        skip: int = 0,
        limit: int = 20,
        active_only: bool = True
    ) -> Dict:
        collection = mongo.resume_templates
        query = {"is_active": True} if active_only else {}
        
        cursor = collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        templates = await cursor.to_list(length=limit)
        
        total = await collection.count_documents(query)
        
        result = [
            TemplateOut(**t).model_dump(by_alias=True) for t in templates
        ]
        
        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} templates",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def list_public_templates(
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None
    ) -> Dict:
        collection = mongo.resume_templates
        
        query = {"is_active": True}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"template_id": {"$regex": search, "$options": "i"}}
            ]
        
        cursor = collection.find(query).skip(skip).limit(limit).sort("name", 1)
        templates = await cursor.to_list(length=limit)
        
        total = await collection.count_documents(query)
        
        result = []
        for t in templates:
            t_copy = t.copy()
            if "_id" in t_copy:
                t_copy["_id"] = str(t_copy["_id"])
            result.append(TemplateOut(**t_copy).model_dump(by_alias=True))
        
        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} active templates",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def get_public_template(template_id: str) -> Dict:
        """
        Public endpoint: Get details of one active template
        """
        collection = mongo.resume_templates
        doc = await collection.find_one({"template_id": template_id, "is_active": True})
        
        if not doc:
            raise HTTPException(
                status_code=404,
                detail="Template not found or inactive"
            )
        
        # Convert _id to string for Pydantic
        doc_safe = doc.copy()
        if "_id" in doc_safe:
            doc_safe["_id"] = str(doc_safe["_id"])
        
        return {
            "status": 200,
            "success": True,
            "message": "Template details retrieved",
            "data": TemplateOut(**doc_safe).model_dump(by_alias=True)
        }


    @staticmethod
    async def get_template(template_id: str) -> Dict:
        collection = mongo.resume_templates
        doc = await collection.find_one({"template_id": template_id, "is_active": True})
        
        if not doc:
            raise HTTPException(404, "Template not found or inactive")
        
        return {
            "status": 200,
            "success": True,
            "message": "Template retrieved",
            "data": TemplateOut(**doc).model_dump(by_alias=True)
        }

    @staticmethod
    async def update_template(template_id: str, update_data: Dict, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(403, "Admin access required")

        collection = mongo.resume_templates
        existing = await collection.find_one({"template_id": template_id})
        if not existing:
            raise HTTPException(404, "Template not found")

        update_data["updated_at"] = datetime.utcnow()
        result = await collection.update_one(
            {"template_id": template_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(400, "No changes applied")

        updated = await collection.find_one({"template_id": template_id})
        return {
            "status": 200,
            "success": True,
            "message": "Template updated",
            "data": TemplateOut(**updated).model_dump(by_alias=True)
        }

    @staticmethod
    async def delete_template(template_id: str, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(403, "Admin access required")

        collection = mongo.resume_templates
        result = await collection.update_one(
            {"template_id": template_id},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )

        if result.modified_count == 0:
            raise HTTPException(404, "Template not found")

        return {
            "status": 200,
            "success": True,
            "message": "Template deactivated (soft delete)"
        }

    # ────────────────────────────────────────────────
    # Schema endpoints (similar structure)
    # ────────────────────────────────────────────────

    @staticmethod
    async def create_schema(schema_data: ResumeSchemaCreate, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(403, "Admin access required")

        collection = mongo.resume_content_schemas
        
        existing = await collection.find_one({"schema_id": schema_data.schema_id})
        if existing:
            raise HTTPException(400, "Schema ID already exists")
        
        now = datetime.utcnow()
        doc = schema_data.model_dump()
        doc.update({
            "_id": schema_data.schema_id,
            "created_at": now,
            "updated_at": now,
            "version": 1
        })
        
        await collection.insert_one(doc)
        return {
            "status": 201,
            "success": True,
            "message": "Schema created",
            "data": ResumeSchemaOut(**doc).model_dump(by_alias=True)
        }

    # ... add list_schemas, get_schema, update_schema, delete_schema similarly ...

    # ────────────────────────────────────────────────
    # User Resume endpoints
    # ────────────────────────────────────────────────

    @staticmethod
    async def create_user_resume(user_id: str, data: UserResumeCreate) -> Dict:

        # 1. Validate template
        template = await mongo.resume_templates.find_one({
            "template_id": data.template_id,
            "is_active": True
        })
        if not template:
            raise HTTPException(400, "Invalid or inactive template_id")

        # 2. Validate schema
        schema = await mongo.resume_content_schemas.find_one({
            "schema_id": data.schema_id
        })
        if not schema:
            raise HTTPException(400, "Invalid schema_id")

        # 3. Prepare document
        now = datetime.utcnow()
        resume_id = str(ObjectId())          # string ID for frontend/URL
        internal_id = ObjectId()             # MongoDB internal _id

        doc = {
            "_id": internal_id,
            "user_id": user_id,
            "resume_id": resume_id,
            "template_id": data.template_id,
            "schema_id": data.schema_id,
            "content": data.content,
            "status": "draft",
            "created_at": now,
            "updated_at": now
        }

        # 4. Insert
        await mongo.user_resumes.insert_one(doc)

        # CRITICAL: Convert ObjectId to string BEFORE Pydantic
        pydantic_safe_doc = doc.copy()  # make a copy so we don't modify original
        pydantic_safe_doc["_id"] = str(pydantic_safe_doc["_id"])

        # 6. Return
        return {
            "status": 201,
            "success": True,
            "message": "Resume created successfully",
            "data": UserResumeOut(**doc_for_pydantic).model_dump(by_alias=True)
        }
        @staticmethod
        async def get_public_template(template_id: str) -> Dict:
            """
            Public endpoint: Get details of one active template
            """
            collection = mongo.resume_templates
            doc = await collection.find_one({"template_id": template_id, "is_active": True})
            
            if not doc:
                raise HTTPException(
                    status_code=404,
                    detail="Template not found or inactive"
                )
            
            return {
                "status": 200,
                "success": True,
                "message": "Template details retrieved",
                "data": TemplateOut(**doc).model_dump(by_alias=True)
            }





    # ────────────────────────────────────────────────
    # Schema Management (Admin-only)
    # ────────────────────────────────────────────────

    @staticmethod
    async def create_schema(schema_data: ResumeSchemaCreate, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(status_code=403, detail="Admin access required")

        collection = mongo.resume_content_schemas
        
        existing = await collection.find_one({"schema_id": schema_data.schema_id})
        if existing:
            raise HTTPException(status_code=400, detail="Schema ID already exists")
        
        now = datetime.utcnow()
        doc = schema_data.model_dump()
        doc.update({
            "_id": schema_data.schema_id,
            "created_at": now,
            "updated_at": now,
            "version": 1
        })
        
        await collection.insert_one(doc)
        
        return {
            "status": 201,
            "success": True,
            "message": "Schema created successfully",
            "data": ResumeSchemaOut(**doc).model_dump(by_alias=True)
        }

    @staticmethod
    async def list_schemas(
        skip: int = 0,
        limit: int = 20,
        active_only: bool = True
    ) -> Dict:
        collection = mongo.resume_content_schemas
        query = {}  # can add "is_active": True later if you add is_active field
        
        cursor = collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        schemas_list = await cursor.to_list(length=limit)
        
        total = await collection.count_documents(query)
        
        result = [
            ResumeSchemaOut(**s).model_dump(by_alias=True) for s in schemas_list
        ]
        
        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} schemas",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def get_schema(schema_id: str) -> Dict:
        collection = mongo.resume_content_schemas
        doc = await collection.find_one({"schema_id": schema_id})
        
        if not doc:
            raise HTTPException(status_code=404, detail="Schema not found")
        
        return {
            "status": 200,
            "success": True,
            "message": "Schema retrieved successfully",
            "data": ResumeSchemaOut(**doc).model_dump(by_alias=True)
        }

    @staticmethod
    async def update_schema(schema_id: str, update_data: Dict, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(status_code=403, detail="Admin access required")

        collection = mongo.resume_content_schemas
        existing = await collection.find_one({"schema_id": schema_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Schema not found")

        update_data["updated_at"] = datetime.utcnow()
        result = await collection.update_one(
            {"schema_id": schema_id},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            raise HTTPException(status_code=400, detail="No changes applied")

        updated = await collection.find_one({"schema_id": schema_id})
        return {
            "status": 200,
            "success": True,
            "message": "Schema updated successfully",
            "data": ResumeSchemaOut(**updated).model_dump(by_alias=True)
        }

    @staticmethod
    async def delete_schema(schema_id: str, current_user: str) -> Dict:
        if not await ResumeController._is_admin(current_user):
            raise HTTPException(status_code=403, detail="Admin access required")

        collection = mongo.resume_content_schemas
        result = await collection.delete_one({"schema_id": schema_id})

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Schema not found")

        return {
            "status": 200,
            "success": True,
            "message": "Schema deleted successfully"
        }

    # ────────────────────────────────────────────────
    # Public Schemas List (no auth)
    # ────────────────────────────────────────────────

    @staticmethod
    async def list_public_schemas(
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None
    ) -> Dict:
        collection = mongo.resume_content_schemas
        
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"schema_id": {"$regex": search, "$options": "i"}}
            ]
        
        cursor = collection.find(query).skip(skip).limit(limit).sort("name", 1)
        schemas_list = await cursor.to_list(length=limit)
        
        total = await collection.count_documents(query)
        
        result = [
            ResumeSchemaOut(**s).model_dump(by_alias=True) for s in schemas_list
        ]
        
        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} schemas",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }



    # ────────────────────────────────────────────────
    # User Resume CRUD
    # ────────────────────────────────────────────────

    @staticmethod
    async def create_user_resume(user_id: str, data: UserResumeCreate) -> Dict:
        template = await mongo.resume_templates.find_one({
            "template_id": data.template_id,
            "is_active": True
        })
        if not template:
            raise HTTPException(400, "Invalid or inactive template_id")

        schema = await mongo.resume_content_schemas.find_one({
            "schema_id": data.schema_id
        })
        if not schema:
            raise HTTPException(400, "Invalid schema_id")

        now = datetime.utcnow()
        resume_id = str(ObjectId())
        internal_id = ObjectId()

        doc = {
            "_id": internal_id,
            "user_id": user_id,
            "resume_id": resume_id,
            "template_id": data.template_id,
            "schema_id": data.schema_id,
            "content": data.content,
            "status": "draft",
            "created_at": now,
            "updated_at": now
        }

        await mongo.user_resumes.insert_one(doc)

        # FIX: Convert ObjectId to string RIGHT HERE
        safe_doc = doc.copy()
        safe_doc["_id"] = str(safe_doc["_id"])

        # Use the SAFE version for Pydantic
        return {
            "status": 201,
            "success": True,
            "message": "Resume created successfully",
            "data": UserResumeOut(**safe_doc).model_dump(by_alias=True)
        }



    @staticmethod
    async def list_user_resumes(
        user_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Dict:
        query = {"user_id": user_id}
        if status:
            query["status"] = status

        cursor = mongo.user_resumes.find(query).skip(skip).limit(limit).sort("updated_at", -1)
        resumes = await cursor.to_list(length=limit)

        total = await mongo.user_resumes.count_documents(query)

        result = []
        for r in resumes:
            r_copy = r.copy()
            if "_id" in r_copy:
                r_copy["_id"] = str(r_copy["_id"])
            result.append(UserResumeOut(**r_copy).model_dump(by_alias=True))

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} resumes",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def get_user_resume(user_id: str, resume_id: str) -> Dict:
        doc = await mongo.user_resumes.find_one({
            "user_id": user_id,
            "resume_id": resume_id
        })

        if not doc:
            raise HTTPException(404, "Resume not found or you don't have access")

        # FIX: convert _id
        doc_copy = doc.copy()
        if "_id" in doc_copy:
            doc_copy["_id"] = str(doc_copy["_id"])

        return {
            "status": 200,
            "success": True,
            "message": "Resume retrieved",
            "data": UserResumeOut(**doc_copy).model_dump(by_alias=True)
        }


    @staticmethod
    async def update_user_resume_content(
        user_id: str,
        resume_id: str,
        content_update: Dict
    ) -> Dict:
        existing = await mongo.user_resumes.find_one({
            "user_id": user_id,
            "resume_id": resume_id
        })

        if not existing:
            raise HTTPException(404, "Resume not found")

        now = datetime.utcnow()
        update_result = await mongo.user_resumes.update_one(
            {"user_id": user_id, "resume_id": resume_id},
            {
                "$set": {
                    "content": content_update,
                    "updated_at": now
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(400, "No changes applied")

        # Fetch the updated document
        updated = await mongo.user_resumes.find_one({
            "user_id": user_id,
            "resume_id": resume_id
        })

        # FIX: Convert _id to string BEFORE passing to Pydantic
        updated_safe = updated.copy()
        if "_id" in updated_safe:
            updated_safe["_id"] = str(updated_safe["_id"])

        return {
            "status": 200,
            "success": True,
            "message": "Resume content updated successfully",
            "data": UserResumeOut(**updated_safe).model_dump(by_alias=True)
        }

    @staticmethod
    async def delete_user_resume(user_id: str, resume_id: str) -> Dict:
        result = await mongo.user_resumes.delete_one({
            "user_id": user_id,
            "resume_id": resume_id
        })

        if result.deleted_count == 0:
            raise HTTPException(404, "Resume not found or already deleted")

        return {
            "status": 200,
            "success": True,
            "message": "Resume deleted successfully"
        }





    @staticmethod
    async def generate_resume(user_id: str, resume_id: str, format: str = "pdf") -> Any:
        resume = await mongo.user_resumes.find_one({
            "user_id": user_id,
            "resume_id": resume_id
        })
        if not resume:
            raise HTTPException(404, "Resume not found")

        template = await mongo.resume_templates.find_one({
            "template_id": resume["template_id"]
        })
        if not template:
            raise HTTPException(400, "Template not found")

        return await ResumeGenerator.generate_resume(resume, template, format)