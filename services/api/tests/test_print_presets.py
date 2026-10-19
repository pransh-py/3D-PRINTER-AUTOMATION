"""A displayed print specification must describe the exact selected profile bundle."""

import json
from asyncio import run
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import select
from test_commerce import seed_commerce

from xxx_api.config import Settings
from xxx_api.models.analysis import AnalysisRun
from xxx_api.models.quotes import QuoteRequest
from xxx_api.print_presets import PresetConfigurationError, load_print_presets
from xxx_api.services.commerce import accept_quote, issue_quote, utc
from xxx_api.services.print_catalogue import available_print_presets
from xxx_api.services.quotes import QuoteRequestConflictError, create_quote_request


def preset_manifest(root: Path) -> Path:
    bundle = root / "standard"
    bundle.mkdir()
    profiles = {
        "machine.json": {"nozzle_diameter": ["0.4"]},
        "process.json": {
            "layer_height": "0.2",
            "sparse_infill_density": "20%",
            "enable_support": "1",
            "wall_loops": "3",
        },
        "filament.json": {"filament_type": ["PLA"]},
    }
    digest = sha256()
    for name, value in profiles.items():
        data = json.dumps(value).encode()
        (bundle / name).write_bytes(data)
        digest.update(name.encode() + b"\0" + data)
    manifest = root / "presets.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "code": "pla-standard",
                    "label": "PLA standard",
                    "materialCode": "pla",
                    "colours": ["White", "Black"],
                    "profileDirectory": str(bundle),
                    "profileSha256": digest.hexdigest(),
                }
            ]
        )
    )
    return manifest


def test_preset_settings_are_read_from_the_pinned_files(tmp_path):
    manifest = preset_manifest(tmp_path)
    settings = Settings(_env_file=None, environment="test", analysis_preset_manifest=manifest)
    preset = load_print_presets(settings)[0]
    spec = preset.specification("White")
    assert spec["presetCode"] == "pla-standard"
    assert spec["colour"] == "White"
    assert spec["settings"] == {
        "nozzleDiameterMm": "0.4",
        "layerHeightMm": "0.2",
        "infillPercent": 20,
        "supports": True,
        "wallLoops": 3,
        "filamentType": "PLA",
    }
    assert "profileDirectory" not in spec
    with pytest.raises(PresetConfigurationError):
        preset.specification("Red")


def test_missing_or_changed_profiles_never_become_orderable(tmp_path):
    manifest = preset_manifest(tmp_path)
    settings = Settings(_env_file=None, environment="test", analysis_preset_manifest=manifest)
    (tmp_path / "standard/process.json").write_text("{}")
    with pytest.raises(PresetConfigurationError):
        load_print_presets(settings)


def test_no_configuration_does_not_invent_a_print_catalogue():
    assert load_print_presets(Settings(_env_file=None, environment="test")) == []


def test_only_priced_presets_are_offered_and_request_retries_preserve_choices(tmp_path):
    async def scenario():
        manifest = preset_manifest(tmp_path)
        entries = json.loads(manifest.read_text())
        entries[0]["materialCode"] = "lab-pla"
        manifest.write_text(json.dumps(entries))
        settings = Settings(
            _env_file=None,
            environment="test",
            analysis_preset_manifest=manifest,
            analysis_slicer_command=Path(__file__).resolve(),
            analysis_slicer_version="test-only",
            analysis_slicer_sha256="a" * 64,
            analysis_slicer_timeout_seconds=10,
        )
        engine, sessions, _, buyer, _, _ = await seed_commerce()
        try:
            async with sessions() as session:
                preset = (await available_print_presets(session, settings))[0]
                specification = preset.specification("White")
                from uuid import uuid4

                token = uuid4()
                request = await create_quote_request(
                    session, buyer=buyer, client_token=token, print_specification=specification
                )
                repeated = await create_quote_request(
                    session, buyer=buyer, client_token=token, print_specification=specification
                )
                assert repeated.id == request.id
                with pytest.raises(QuoteRequestConflictError):
                    await create_quote_request(
                        session,
                        buyer=buyer,
                        client_token=token,
                        print_specification=preset.specification("Black"),
                    )
                entries[0]["materialCode"] = "unpriced-material"
                manifest.write_text(json.dumps(entries))
                assert await available_print_presets(session, settings) == []
        finally:
            await engine.dispose()

    run(scenario())


def test_final_quote_and_accepted_order_freeze_selected_specification(tmp_path):
    async def scenario():
        manifest = preset_manifest(tmp_path)
        specification = load_print_presets(
            Settings(_env_file=None, environment="test", analysis_preset_manifest=manifest)
        )[0].specification("Black")
        specification["materialCode"] = "lab-pla"
        engine, sessions, owner, buyer, request, estimate = await seed_commerce()
        try:
            async with sessions() as session:
                persisted = await session.get(QuoteRequest, request.id)
                persisted.print_specification = specification
                analysis = await session.scalar(select(AnalysisRun))
                analysis.profile_sha256 = specification["profileSha256"]
                analysis.print_preset_code = specification["presetCode"]
                await session.commit()
                quote = await issue_quote(
                    session,
                    owner=owner,
                    request_id=request.id,
                    estimate_id=estimate.id,
                    expected_version=4,
                    expires_at=utc() + timedelta(hours=1),
                )
                assert quote.print_specification == specification
                order = await accept_quote(session, buyer=buyer, quote_id=quote.id)
                assert order.commercial_snapshot["schemaVersion"] == 2
                assert order.print_specification == specification
        finally:
            await engine.dispose()

    run(scenario())


def test_automatic_estimate_recovers_completed_analysis_without_impersonating_owner():
    from sqlalchemy import delete, func

    from xxx_api.domain.quotes import QuoteRequestStatus
    from xxx_api.models.pricing import QuoteEstimate
    from xxx_api.services.pricing import create_pending_estimates

    async def scenario():
        engine, sessions, _, _, request, _ = await seed_commerce()
        try:
            async with sessions() as session:
                await session.execute(delete(QuoteEstimate))
                persisted = await session.get(QuoteRequest, request.id)
                persisted.status = QuoteRequestStatus.ANALYSIS_READY
                persisted.version = 3
                analysis = await session.scalar(select(AnalysisRun))
                analysis.print_preset_code = "pla-standard"
                persisted.print_specification = {
                    "presetCode": "pla-standard",
                    "profileSha256": analysis.profile_sha256,
                    "materialCode": analysis.material_code,
                }
                await session.commit()
                assert await create_pending_estimates(session) == 1
                estimate = await session.scalar(select(QuoteEstimate))
                assert estimate.created_by_user_id is None
                assert estimate.analysis_run_id == analysis.id
                assert estimate.filament_mg > 0
                assert persisted.status is QuoteRequestStatus.ESTIMATE_READY
                assert await create_pending_estimates(session) == 0
                assert await session.scalar(select(func.count(QuoteEstimate.id))) == 1
        finally:
            await engine.dispose()

    run(scenario())
