from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import CurrentUser, unauthorized
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Authentification"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Échange un email et un mot de passe contre un jeton JWT (HS256, durée limitée) à envoyer
    ensuite dans l'en-tête `Authorization: Bearer <token>`. Le message d'erreur est volontairement
    identique que l'email existe ou non. Limité à 5 échecs par IP toutes les 15 minutes (429)."""
    email = payload.email.strip().lower()
    user = db.scalar(select(models.User).where(models.User.email == email))
    if not verify_password(payload.password, user.password_hash if user else None):
        raise unauthorized("Email ou mot de passe incorrect")
    token, expires_in = create_access_token(user.id, user.email, user.role.value)
    return schemas.TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=schemas.UserRead)
def me(user: CurrentUser):
    """Profil de l'utilisateur authentifié."""
    return user
