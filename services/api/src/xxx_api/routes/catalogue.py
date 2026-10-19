"""Public print choices contain no paths, credentials, pricing secrets or stock guesses."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from xxx_api.config import Settings
from xxx_api.dependencies import DatabaseSession, get_runtime_settings
from xxx_api.print_presets import PresetConfigurationError
from xxx_api.services.print_catalogue import available_print_presets

router = APIRouter(tags=["catalogue"])
RuntimeSettings = Annotated[Settings, Depends(get_runtime_settings)]


@router.get("/print-presets")
async def print_presets(
    session: DatabaseSession, settings: RuntimeSettings, response: Response
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    try:
        presets = await available_print_presets(session, settings)
    except PresetConfigurationError as error:
        raise HTTPException(
            503, "Print options are temporarily unavailable. Please try again."
        ) from error
    return {
        "items": [preset.public() for preset in presets],
        "message": None
        if presets
        else "The owner is configuring print options and prices. Please check back shortly.",
    }
