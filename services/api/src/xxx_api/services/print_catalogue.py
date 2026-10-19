"""Expose only reviewed profiles that can be priced by the active owner rate card."""

from functools import partial

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xxx_api.config import Settings
from xxx_api.domain.pricing import PricingPolicyStatus
from xxx_api.models.pricing import MaterialRate, PricingPolicy
from xxx_api.print_presets import PrintPreset, load_print_presets


async def available_print_presets(session: AsyncSession, settings: Settings) -> list[PrintPreset]:
    presets = await to_thread.run_sync(partial(load_print_presets, settings))
    if not settings.analysis_slicer_command:
        return []
    materials = set(
        await session.scalars(
            select(MaterialRate.code)
            .join(PricingPolicy)
            .where(PricingPolicy.status == PricingPolicyStatus.ACTIVE)
        )
    )
    return [preset for preset in presets if preset.material_code in materials]
