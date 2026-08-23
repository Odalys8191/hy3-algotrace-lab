from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_artifacts_catalog import bundle, record, record_payload

import hy3_algotrace.artifacts as artifacts_module
import hy3_algotrace.catalog as catalog_module
import hy3_algotrace.codecontests as codecontests_module
from hy3_algotrace.artifacts import (
    ArtifactExistsError,
    ArtifactStore,
    ArtifactStoreError,
    sha256_json,
)
from hy3_algotrace.catalog import BundleValidationError, ProblemCatalog, load_pilot_bundles
from hy3_algotrace.codecontests import (
    CodeContestsImportError,
    build_selection_manifest,
    load_codecontests_json,
    select_formal_bundles,
    validate_selection_manifest,
)


def _raw_codecontests_record() -> dict[str, object]:
    return {
        "name": "Largest value",
        "description": "Read two integers and print the larger one.",
        "source": "CODEFORCES",
        "cf_contest_id": 1000,
        "cf_index": "A",
        "cf_rating": 1300,
        "cf_tags": ["greedy"],
        "time_limit": {"seconds": "2", "nanos": 500_000_000},
        "memory_limit_bytes": 268_435_456,
        "input_file": "",
        "output_file": "",
        "public_tests": [{"input": "1 2\n", "output": "2\n"}],
        "private_tests": [{"input": "4 3\n", "output": "4\n"}],
        "source_url": "https://codeforces.com/problemset/problem/1000/A",
    }


def test_artifact_store_keeps_writes_inside_trusted_dirfd_during_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    safe_directory = root / "safe"
    safe_directory.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    store = ArtifactStore(root)
    target = safe_directory / "value.json"
    real_open = artifacts_module.os.open
    swapped = False

    def swap_before_absolute_target_open(path: object, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if path == target and not swapped:
            swapped = True
            safe_directory.rmdir()
            safe_directory.symlink_to(outside, target_is_directory=True)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(artifacts_module.os, "open", swap_before_absolute_target_open)

    store.write_json("safe/value.json", {"schema_version": "1.2"})

    assert not swapped
    assert safe_directory.is_dir()
    assert not safe_directory.is_symlink()
    assert not (outside / "value.json").exists()


def test_artifact_store_publishes_a_complete_temp_file_only_at_final_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path)
    observed = False
    real_link = artifacts_module.os.link

    def observe_publish(*args: object, **kwargs: object) -> None:
        nonlocal observed
        observed = True
        assert not (tmp_path / "safe" / "value.json").exists()
        real_link(*args, **kwargs)

    monkeypatch.setattr(artifacts_module.os, "link", observe_publish)

    store.write_json("safe/value.json", {"schema_version": "1.2", "payload": "complete"})

    assert observed
    assert (tmp_path / "safe" / "value.json").is_file()


def test_codecontests_mapping_derives_provenance_from_raw_fields_and_context(
    tmp_path: Path,
) -> None:
    source = tmp_path / "codecontests.json"
    source.write_text(json.dumps([_raw_codecontests_record()]), encoding="utf-8")

    loaded = load_codecontests_json(source, split="test")

    assert loaded[0].problem_id == "cf-1000-a"
    assert loaded[0].source_split == "test"
    assert loaded[0].source_url == "https://codeforces.com/problemset/problem/1000/A"
    assert loaded[0].time_limit_ms == 2_500
    assert loaded[0].memory_limit_mb == 256
    assert loaded[0].hidden_tests[0].test_id == "hidden-1"


@pytest.mark.parametrize("source_value", ("CODEFORCES", 2))
def test_codecontests_protobuf_json_accepts_only_official_codeforces_sources(
    tmp_path: Path, source_value: object
) -> None:
    raw = _raw_codecontests_record()
    raw["source"] = source_value
    source = tmp_path / "codecontests.json"
    source.write_text(json.dumps([raw]), encoding="utf-8")

    imported = load_codecontests_json(source, split="validation")

    assert imported[0].source == "codeforces"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source", "CODECHEF"),
        ("source", None),
        ("source", 1),
        ("source", 2.0),
        ("is_description_translated", 0),
        ("input_file", "input.txt"),
        ("output_file", "output.txt"),
        ("time_limit", {"seconds": 0, "nanos": 0}),
        ("time_limit", {"seconds": -1, "nanos": 0}),
        ("time_limit", {"seconds": 1, "nanos": -1}),
        ("time_limit", {"seconds": 1, "nanos": 1_000_000_000}),
    ),
)
def test_codecontests_protobuf_json_rejects_nonformal_source_io_and_duration(
    tmp_path: Path, field: str, value: object
) -> None:
    raw = _raw_codecontests_record()
    raw[field] = value
    source = tmp_path / "codecontests.jsonl"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CodeContestsImportError):
        load_codecontests_json(source, split="validation")


def test_codecontests_mapping_rejects_url_that_does_not_match_contest_and_index(
    tmp_path: Path,
) -> None:
    raw = _raw_codecontests_record()
    raw["source_url"] = "https://codeforces.com/problemset/problem/999/A"
    source = tmp_path / "codecontests.jsonl"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CodeContestsImportError, match="URL"):
        load_codecontests_json(source, split="validation")


def test_prevalidated_problem_json_rejects_bool_integer_before_hashing(
    tmp_path: Path,
) -> None:
    payload = record_payload()
    payload["time_limit_ms"] = True
    normalized = {key: value for key, value in payload.items() if key != "content_hash"}
    normalized["time_limit_ms"] = 1
    payload["content_hash"] = sha256_json(normalized)
    source = tmp_path / "problem-record.json"
    source.write_text(json.dumps([payload]), encoding="utf-8")

    with pytest.raises(CodeContestsImportError, match="strict JSON types"):
        load_codecontests_json(source, split="validation")


def test_catalog_fails_closed_for_unknown_directory(tmp_path: Path) -> None:
    (tmp_path / "unexpected").mkdir()

    with pytest.raises(BundleValidationError, match="unknown catalog entry"):
        ProblemCatalog.from_directory(tmp_path)


def _write_formal_bundle(root: Path, name: str, item: object) -> Path:
    directory = root / name
    directory.mkdir()
    formal = item
    for filename, value in (
        ("problem.json", formal.record.model_dump(mode="json")),
        ("oracle.json", formal.oracle.model_dump(mode="json")),
        ("gold_trace.json", formal.gold_trace.model_dump(mode="json")),
    ):
        (directory / filename).write_text(json.dumps(value), encoding="utf-8")
    (directory / "reference.cpp").write_text(formal.reference_cpp, encoding="utf-8")
    return directory


def test_catalog_rejects_root_subdirectory_symlink(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    outside = tmp_path / "outside"
    _write_formal_bundle(tmp_path, "outside", bundle())
    (catalog_root / "linked-bundle").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BundleValidationError, match="symlink"):
        ProblemCatalog.from_directory(catalog_root)


@pytest.mark.parametrize(
    "member", ("problem.json", "oracle.json", "gold_trace.json", "reference.cpp")
)
def test_catalog_rejects_symlinked_bundle_member(tmp_path: Path, member: str) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    directory = _write_formal_bundle(catalog_root, "bundle", bundle())
    target = tmp_path / f"outside-{member}"
    shutil.copyfile(directory / member, target)
    (directory / member).unlink()
    (directory / member).symlink_to(target)

    with pytest.raises(BundleValidationError, match="symlink"):
        ProblemCatalog.from_directory(catalog_root)


def test_catalog_reads_open_bundle_dirfd_after_bundle_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = bundle()
    root = tmp_path / "catalog"
    root.mkdir()
    directory = _write_formal_bundle(root, "bundle", original)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_formal_bundle(outside, "replacement", bundle())
    replacement = outside / "replacement"
    saved = root / "bundle-before-swap"
    real_open = catalog_module.os.open
    swapped = False

    def swap_bundle_path(path: object, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if path == "problem.json" and not swapped and kwargs.get("dir_fd") is not None:
            directory.rename(saved)
            directory.symlink_to(replacement, target_is_directory=True)
            swapped = True
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(catalog_module.os, "open", swap_bundle_path)

    catalog = ProblemCatalog.from_directory(root)

    assert swapped
    assert catalog.get_bundle(original.record.problem_id).record == original.record


@pytest.mark.parametrize("member", ("problem.json", "gold_trace.json"))
def test_catalog_rejects_bool_for_integer_disk_fields_before_hashing(
    tmp_path: Path, member: str
) -> None:
    directory = _write_formal_bundle(tmp_path, "bundle", bundle())
    path = directory / member
    payload = json.loads(path.read_text(encoding="utf-8"))
    if member == "problem.json":
        payload["time_limit_ms"] = True
        normalized = {key: value for key, value in payload.items() if key != "content_hash"}
        normalized["time_limit_ms"] = 1
        payload["content_hash"] = sha256_json(normalized)
    else:
        payload["steps"][0]["step_number"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BundleValidationError, match="strict JSON types"):
        ProblemCatalog.from_directory(tmp_path)


def test_pilot_bundles_are_versioned_loadable_and_ineligible_for_formal_selection() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "pilots"

    pilots = load_pilot_bundles(fixture_root)

    assert len(pilots) == 5
    assert all(not pilot.formal_selection_eligible for pilot in pilots)
    assert all(pilot.public_tests and pilot.hidden_tests for pilot in pilots)
    with pytest.raises(CodeContestsImportError, match="pilot"):
        select_formal_bundles(pilots)


@pytest.mark.parametrize("member", ("pilot.json", "gold_trace.json"))
def test_pilot_loader_rejects_bool_for_integer_disk_fields_before_hashing(
    tmp_path: Path, member: str
) -> None:
    root = _copy_pilot_fixture(tmp_path)
    path = root / "max-two" / member
    payload = json.loads(path.read_text(encoding="utf-8"))
    if member == "pilot.json":
        payload["time_limit_ms"] = True
        normalized = {key: value for key, value in payload.items() if key != "content_hash"}
        normalized["time_limit_ms"] = 1
        payload["content_hash"] = sha256_json(normalized)
    else:
        payload["steps"][0]["step_number"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BundleValidationError, match="strict JSON types"):
        load_pilot_bundles(root)


def _copy_pilot_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "pilots"
    destination = tmp_path / "pilots"
    shutil.copytree(source, destination)
    return destination


def _write_pilot_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_pilot_manifest_forbids_unknown_fields(tmp_path: Path) -> None:
    root = _copy_pilot_fixture(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    _write_pilot_manifest(root, manifest)

    with pytest.raises(BundleValidationError, match="extra"):
        load_pilot_bundles(root)


def test_pilot_manifest_rejects_duplicate_component_name(tmp_path: Path) -> None:
    root = _copy_pilot_fixture(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["bundles"][1] = manifest["bundles"][0]
    _write_pilot_manifest(root, manifest)

    with pytest.raises(BundleValidationError, match="unique"):
        load_pilot_bundles(root)


@pytest.mark.parametrize("unsafe_name", ("../outside", "/tmp/outside"))
def test_pilot_manifest_rejects_non_component_bundle_path(
    tmp_path: Path, unsafe_name: str
) -> None:
    root = _copy_pilot_fixture(tmp_path)
    outside = tmp_path / "outside"
    shutil.copytree(root / "max-two", outside)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["bundles"][0] = str(outside) if unsafe_name.startswith("/") else unsafe_name
    _write_pilot_manifest(root, manifest)

    with pytest.raises(BundleValidationError, match="single path component"):
        load_pilot_bundles(root)


def test_pilot_loader_rejects_symlinked_declared_bundle(tmp_path: Path) -> None:
    root = _copy_pilot_fixture(tmp_path)
    bundle_directory = root / "max-two"
    outside = tmp_path / "outside"
    bundle_directory.rename(outside)
    bundle_directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BundleValidationError, match="symlink"):
        load_pilot_bundles(root)


def test_pilot_loader_rejects_undeclared_bundle_directory(tmp_path: Path) -> None:
    root = _copy_pilot_fixture(tmp_path)
    shutil.copytree(root / "max-two", root / "undeclared")

    with pytest.raises(BundleValidationError, match="undeclared"):
        load_pilot_bundles(root)


def test_pilot_loader_rejects_duplicate_problem_ids(tmp_path: Path) -> None:
    root = _copy_pilot_fixture(tmp_path)
    shutil.rmtree(root / "max-two")
    shutil.copytree(root / "sum-pair", root / "duplicate")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["bundles"][0] = "duplicate"
    _write_pilot_manifest(root, manifest)

    with pytest.raises(BundleValidationError, match="unique problem IDs"):
        load_pilot_bundles(root)


def test_frozen_manifest_forbids_unknown_fields_and_detects_component_hash_mutation() -> None:
    bundles = []
    counter = 1000
    for topic in (
        "construction_simulation",
        "greedy",
        "binary_search",
        "dynamic_programming",
        "graph",
    ):
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                payload = record_payload(
                    problem_id=f"cf-{counter}-a",
                    topic=codecontests_module.Topic(topic),
                    rating=rating,
                )
                payload["cf_contest_id"] = counter
                payload["source_url"] = (
                    f"https://codeforces.com/problemset/problem/{counter}/A"
                )
                payload["content_hash"] = sha256_json(
                    {key: value for key, value in payload.items() if key != "content_hash"}
                )
                bundles.append(bundle(codecontests_module.ProblemRecord.model_validate(payload)))
                counter += 1
    manifest = build_selection_manifest(bundles).model_dump(mode="json")

    assert validate_selection_manifest(manifest, bundles)[0].record.problem_id == "cf-1000-a"
    with pytest.raises(CodeContestsImportError, match="extra"):
        validate_selection_manifest({**manifest, "unreviewed": True}, bundles)
    manifest["bundles"][0]["reference_cpp_hash"] = "0" * 64
    with pytest.raises(CodeContestsImportError, match="hash"):
        validate_selection_manifest(manifest, bundles)


def test_cli_returns_stable_nonzero_message_on_immutable_write_conflict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(codecontests_module, "load_codecontests_json", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(codecontests_module, "select_formal_problems", lambda _records: ())
    monkeypatch.setattr(
        codecontests_module.ProblemCatalog,
        "from_directory",
        lambda _root: object(),
    )

    def conflict(*_args: object, **_kwargs: object) -> Path:
        raise ArtifactExistsError("artifact already exists: selection/hash.json")

    monkeypatch.setattr(codecontests_module, "write_selection_manifest", conflict)

    assert (
        codecontests_module.main(
            ["input.json", "out", "--split", "test", "--catalog-root", "catalog"]
        )
        == 1
    )
    assert "immutable selection manifest already exists" in capsys.readouterr().err


def test_cli_rejects_same_id_catalog_record_from_another_split(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    imported = record(source_split="test")
    replacement = record(source_split="validation")
    wrote_manifest = False

    monkeypatch.setattr(
        codecontests_module,
        "load_codecontests_json",
        lambda *_args, **_kwargs: (imported,),
    )
    monkeypatch.setattr(
        codecontests_module,
        "select_formal_problems",
        lambda records: tuple(records),
    )
    monkeypatch.setattr(
        codecontests_module.ProblemCatalog,
        "from_directory",
        lambda _root: ProblemCatalog((bundle(replacement),)),
    )

    def write_manifest(*_args: object, **_kwargs: object) -> Path:
        nonlocal wrote_manifest
        wrote_manifest = True
        return Path("selection.json")

    monkeypatch.setattr(codecontests_module, "write_selection_manifest", write_manifest)

    assert (
        codecontests_module.main(
            ["input.json", "out", "--split", "test", "--catalog-root", "catalog"]
        )
        == 1
    )
    assert not wrote_manifest
    assert capsys.readouterr().err == "error: unable to validate and freeze selection\n"


@pytest.mark.parametrize("contents", (b"\xff", b"{"))
def test_cli_sanitizes_invalid_utf8_and_json_as_one_stable_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    contents: bytes,
) -> None:
    source = tmp_path / "sensitive-dataset-name.json"
    source.write_bytes(contents)

    assert (
        codecontests_module.main(
            [
                str(source),
                str(tmp_path / "out"),
                "--split",
                "test",
                "--catalog-root",
                str(tmp_path / "catalog"),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: unable to validate and freeze selection\n"


@pytest.mark.parametrize(
    "failure_kind",
    ("artifact", "validation", "filesystem", "bundle", "import"),
)
def test_cli_sanitizes_expected_boundary_failures_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_kind: str,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> tuple[()]:
        if failure_kind == "artifact":
            raise ArtifactStoreError("secret/output/path\nsecond line")
        if failure_kind == "validation":
            codecontests_module.FrozenSelectionManifest.model_validate({})
        if failure_kind == "filesystem":
            raise OSError("secret/input/path\nsecond line")
        if failure_kind == "bundle":
            raise BundleValidationError("secret bundle detail\nsecond line")
        raise CodeContestsImportError("secret dataset detail\nsecond line")

    monkeypatch.setattr(codecontests_module, "load_codecontests_json", fail)

    assert (
        codecontests_module.main(
            ["input.json", "out", "--split", "test", "--catalog-root", "catalog"]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: unable to validate and freeze selection\n"
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("control_flow", ("keyboard", "system-exit"))
def test_cli_does_not_swallow_control_flow_exceptions(
    monkeypatch: pytest.MonkeyPatch, control_flow: str
) -> None:
    def stop(*_args: object, **_kwargs: object) -> tuple[()]:
        if control_flow == "keyboard":
            raise KeyboardInterrupt
        raise SystemExit(9)

    monkeypatch.setattr(codecontests_module, "load_codecontests_json", stop)

    expected = KeyboardInterrupt if control_flow == "keyboard" else SystemExit
    with pytest.raises(expected) as captured:
        codecontests_module.main(
            ["input.json", "out", "--split", "test", "--catalog-root", "catalog"]
        )
    if control_flow == "system-exit":
        assert captured.value.code == 9


def test_cli_sanitizes_stdout_oserror(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        codecontests_module, "load_codecontests_json", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(codecontests_module, "select_formal_problems", lambda _records: ())
    monkeypatch.setattr(
        codecontests_module.ProblemCatalog,
        "from_directory",
        lambda _root: object(),
    )
    monkeypatch.setattr(
        codecontests_module,
        "write_selection_manifest",
        lambda *_args, **_kwargs: Path("selection.json"),
    )
    real_print = print

    def fail_stdout(*args: object, **kwargs: object) -> None:
        if kwargs.get("file") is None:
            raise OSError("sensitive stdout detail")
        real_print(*args, **kwargs)

    monkeypatch.setattr(codecontests_module, "print", fail_stdout, raising=False)

    assert (
        codecontests_module.main(
            ["input.json", "out", "--split", "test", "--catalog-root", "catalog"]
        )
        == 1
    )
    assert capsys.readouterr().err == "error: unable to validate and freeze selection\n"
