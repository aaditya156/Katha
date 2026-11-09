import logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.exceptions import KathaException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("katha_studio")

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Agentic Multilingual Audio-Story Generation Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(KathaException)
async def katha_exception_handler(request: Request, exc: KathaException) -> JSONResponse:
    """Transform domain exceptions into RFC 7807 Problem Details response."""
    return JSONResponse(
        status_code=exc.status_code,
        headers={"Content-Type": "application/problem+json"},
        content={
            "type": exc.error_type,
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "error_code": exc.error_code,
            "extras": exc.extras,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Transform Pydantic request validation errors into RFC 7807 Problem Details."""
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        headers={"Content-Type": "application/problem+json"},
        content={
            "type": "https://errors.katha.studio/validation-error",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request body or query parameter validation failed.",
            "error_code": "VALIDATION_ERROR",
            "extras": {"validation_errors": errors},
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all unhandled exception handler logging critical error without silent swallow."""
    logger.critical(
        f"Unhandled server exception: {exc}",
        extra={"path": request.url.path, "method": request.method},
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers={"Content-Type": "application/problem+json"},
        content={
            "type": "https://errors.katha.studio/internal-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected server error occurred. Please contact engineering support.",
            "error_code": "INTERNAL_SERVER_ERROR",
            "extras": {"error_type": type(exc).__name__},
        },
    )


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }


app.include_router(api_v1_router, prefix=settings.API_V1_STR)
