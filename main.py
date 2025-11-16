import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr

from database import create_document, get_documents, db

app = FastAPI(title="AI Job Application Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------ Models (request/response) ------------
class ProfileIn(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    resume_text: Optional[str] = None
    titles: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    remote: bool = True
    include_keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)


class JobSearchResult(BaseModel):
    title: str
    company: Optional[str] = None
    url: str
    snippet: Optional[str] = None
    source: str = "google_cse"


class ApplyRequest(BaseModel):
    job_title: str
    company: Optional[str] = None
    job_url: str
    applicant_email: EmailStr


class ApplicationOut(BaseModel):
    job_title: str
    company: Optional[str] = None
    job_url: str
    applicant_email: EmailStr
    status: str
    cover_letter: Optional[str] = None
    notes: Optional[str] = None
    followup_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ------------ Health & Utility ------------
@app.get("/")
def read_root():
    return {"message": "AI Job Application Automation API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# ------------ Profile Endpoints ------------
@app.post("/api/profile")
def save_profile(payload: ProfileIn):
    # Upsert by email (simple approach):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    profile = payload.model_dump()
    profile["type"] = "profile"
    profile["key"] = f"profile:{payload.email}"
    profile["updated_at"] = datetime.now(timezone.utc)
    existing = db["profile"].find_one({"key": profile["key"]})
    if existing:
        db["profile"].update_one({"_id": existing["_id"]}, {"$set": profile})
        return {"ok": True, "updated": True}
    else:
        create_document("profile", profile)
        return {"ok": True, "created": True}


@app.get("/api/profile")
def get_profile(email: EmailStr = Query(...)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    key = f"profile:{email}"
    doc = db["profile"].find_one({"key": key})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    doc["_id"] = str(doc["_id"])  # make JSON safe
    return doc


# ------------ Google CSE Search ------------
JOB_BOARD_DOMAINS = {
    "indeed.com",
    "linkedin.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "monster.com",
    "hired.com",
    "levels.fyi",
    "angel.co",
    "wellfound.com",
}


def is_company_site(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        return not any(b in hostname for b in JOB_BOARD_DOMAINS)
    except Exception:
        return True


@app.get("/api/search", response_model=List[JobSearchResult])
def google_job_search(q: str = Query(..., description="Search query")):
    api_key = os.getenv("GOOGLE_CSE_KEY")
    cx = os.getenv("GOOGLE_CSE_CX")
    if not api_key or not cx:
        raise HTTPException(status_code=500, detail="Google CSE not configured. Set GOOGLE_CSE_KEY and GOOGLE_CSE_CX.")

    params = {"key": api_key, "cx": cx, "q": q}
    r = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Google CSE error: {r.text[:200]}")

    items = r.json().get("items", [])
    results: List[JobSearchResult] = []
    for it in items:
        link = it.get("link")
        title = it.get("title")
        snippet = it.get("snippet")
        if not link or not title:
            continue
        if not is_company_site(link):
            continue
        results.append(JobSearchResult(title=title, url=link, snippet=snippet))

    return results


# ------------ AI Cover Letter (optional OpenAI) ------------

def generate_cover_letter(job_title: str, company: Optional[str], resume_text: Optional[str]) -> str:
    prompt = (
        f"Write a concise, friendly cover letter for the role '{job_title}'"
        + (f" at {company}." if company else ".")
        + " Focus on relevant impact, keep it under 180 words."
    )
    if resume_text:
        prompt += " Use the following resume context where relevant: " + resume_text[:1500]

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Fallback template
        return (
            f"Dear Hiring Team{f' at {company}' if company else ''},\n\n"
            f"I'm excited to apply for the {job_title} role. My background aligns closely with the requirements, "
            f"and I'm confident I can contribute immediately. I'd love to share more about relevant projects and "
            f"how I can support your goals.\n\nBest regards,\n"
        )

    try:
        # Use OpenAI Chat Completions via HTTP to avoid extra dependency
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that writes concise cover letters."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", json=body, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        else:
            return generate_cover_letter.__defaults__[0] if generate_cover_letter.__defaults__ else prompt
    except Exception:
        return (
            f"Dear Hiring Team{f' at {company}' if company else ''},\n\n"
            f"I'm excited to apply for the {job_title} role and believe my experience is a strong fit.\n\nBest,\n"
        )


# ------------ Applications ------------
@app.post("/api/applications", response_model=ApplicationOut)
def create_application(req: ApplyRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Fetch profile (if exists) for resume context
    profile = db["profile"].find_one({"key": f"profile:{req.applicant_email}"})
    resume_text = profile.get("resume_text") if profile else None

    cover_letter = generate_cover_letter(req.job_title, req.company, resume_text)

    doc: Dict[str, Any] = {
        "job_title": req.job_title,
        "company": req.company,
        "job_url": req.job_url,
        "applicant_email": str(req.applicant_email),
        "status": "applied",
        "cover_letter": cover_letter,
        "notes": None,
        "followup_at": datetime.now(timezone.utc) + timedelta(days=int(os.getenv("FOLLOWUP_DAYS", 8))),
    }
    create_document("application", doc)

    return ApplicationOut(**doc)


@app.get("/api/applications", response_model=List[ApplicationOut])
def list_applications(email: Optional[EmailStr] = Query(None)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    filt = {"applicant_email": str(email)} if email else {}
    docs = get_documents("application", filt, limit=100)
    for d in docs:
        d.pop("_id", None)
    return docs


# Simple follow-up trigger (no external send to keep MVP safe)
@app.post("/api/followups/send")
def send_followup(email: EmailStr, job_url: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["application"].find_one({"applicant_email": str(email), "job_url": job_url})
    if not doc:
        raise HTTPException(status_code=404, detail="Application not found")

    # Here you could integrate SendGrid/Gmail. For MVP we just mark as sent.
    db["application"].update_one({"_id": doc["_id"]}, {"$set": {"status": "followup_sent", "updated_at": datetime.now(timezone.utc)}})
    return {"ok": True, "status": "followup_sent"}


# Optional: simple schema info for viewers
@app.get("/schema")
def schema_info():
    return {
        "collections": [
            {
                "name": "profile",
                "fields": ["name", "email", "phone", "resume_text", "titles", "locations", "remote", "include_keywords", "exclude_keywords"],
            },
            {
                "name": "application",
                "fields": ["job_title", "company", "job_url", "applicant_email", "status", "cover_letter", "notes", "followup_at"],
            },
        ]
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
