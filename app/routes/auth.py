from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.auth import authenticate_user
from app.dependencies import CsrfRequired, get_db_session, render

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db_session),
    _: None = CsrfRequired,
):
    user = authenticate_user(db, username, password)

    if not user:
        return render(request, "login.html", {"error": "Invalid username or password."})

    request.session["user_id"] = user.id

    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(
    request: Request,
    _: None = CsrfRequired,
):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
