"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal

# Example schemas (kept for reference):

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    """
    Products collection schema
    Collection name: "product" (lowercase of class name)
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")

# App-specific schemas

class UserProfile(BaseModel):
    """User profile and base info"""
    name: str
    email: EmailStr
    phone: Optional[str] = None
    resume_text: Optional[str] = Field(None, description="Parsed resume text or paste-in")

class JobPreference(BaseModel):
    """Preferences for job discovery"""
    titles: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    remote: bool = True
    include_keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)

class JobPosting(BaseModel):
    """Discovered job posting summary"""
    title: str
    company: Optional[str] = None
    url: str
    snippet: Optional[str] = None
    source: Literal["google_cse", "manual"] = "google_cse"

class Application(BaseModel):
    """An application record"""
    job_title: str
    company: Optional[str] = None
    job_url: str
    applicant_email: EmailStr
    status: Literal["queued", "applied", "followup_scheduled", "followup_sent", "error"] = "queued"
    cover_letter: Optional[str] = None
    notes: Optional[str] = None

# Note: The Flames database viewer will automatically:
# 1. Read these schemas from GET /schema endpoint
# 2. Use them for document validation when creating/editing
# 3. Handle all database operations (CRUD) directly
# 4. You don't need to create any database endpoints!
