import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app import models
from app.database import Base, SessionLocal, engine


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage : python scripts/promote_admin.py <email>")
    email = sys.argv[1].strip().lower()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        user = db.scalar(select(models.User).where(models.User.email == email))
        if user is None:
            sys.exit(f"Aucun utilisateur avec l'email {email}")
        user.role = models.Role.admin
        db.commit()
    print(f"{email} est maintenant administrateur")


if __name__ == "__main__":
    main()
