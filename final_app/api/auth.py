"""Authentication routes for signup and signin."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import bcrypt

from ..database import get_db
from ..models.orm import User
from ..models.schemas import UserSignUp, UserSignIn, UserResponse, AuthResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserSignUp, db: AsyncSession = Depends(get_db)):
    """Register a new user.

    - Email must be unique
    - Password is hashed before storage
    - Access level defaults to 'public'
    """
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered. Please sign in instead."
        )

    # Create new user with hashed password
    new_user = User(
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        tenant_id=user_data.tenant_id,
        department=user_data.department,
        role=user_data.role,
        tier=user_data.tier,
        access_level="public",
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return AuthResponse(
        user=UserResponse.model_validate(new_user),
        message="Account created successfully!"
    )


@router.post("/signin", response_model=AuthResponse)
async def signin(credentials: UserSignIn, db: AsyncSession = Depends(get_db)):
    """Sign in an existing user.

    - Validates email exists
    - Verifies password against stored hash
    """
    # Find user by email
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    return AuthResponse(
        user=UserResponse.model_validate(user),
        message="Signed in successfully!"
    )


@router.get("/me/{user_id}", response_model=UserResponse)
async def get_current_user(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get user by ID."""
    from uuid import UUID

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
