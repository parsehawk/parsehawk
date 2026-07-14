from __future__ import annotations

from importlib.metadata import version

from parsehawk.server.api.fastapi.app import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
EXPECTED_OPERATION_IDS = {
    "cancelJob",
    "configureProvider",
    "createExtractor",
    "createJob",
    "deleteExtractor",
    "deleteFile",
    "deleteJob",
    "downloadFileContent",
    "getApiRoot",
    "getExtractor",
    "getFile",
    "getHealth",
    "getJob",
    "getProvider",
    "listExtractors",
    "listFiles",
    "listJobs",
    "listProviderModels",
    "listProviders",
    "updateExtractor",
    "uploadFile",
    "upsertExtractor",
    "validateSchema",
}


def _operations() -> list[dict[str, object]]:
    document = app.openapi()
    return [
        operation
        for path_item in document["paths"].values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]


def test_openapi_metadata_is_public_and_versioned() -> None:
    document = app.openapi()

    assert version("parsehawk") == "0.2.1"
    assert document["openapi"] == "3.1.0"
    assert document["info"]["title"] == "ParseHawk API"
    assert document["info"]["version"] == "0.2.1"
    assert document["info"]["license"]["identifier"] == "Apache-2.0"
    assert document["servers"] == [
        {
            "url": "http://127.0.0.1:8000",
            "description": "Default local ParseHawk API",
        }
    ]
    assert document["security"] == []


def test_every_operation_has_stable_documentation_metadata() -> None:
    operations = _operations()
    operation_ids = {operation["operationId"] for operation in operations}

    assert operation_ids == EXPECTED_OPERATION_IDS
    for operation in operations:
        assert operation.get("summary")
        assert operation.get("description")
        assert operation.get("tags")

        responses = operation.get("responses")
        assert isinstance(responses, dict)
        assert "500" in responses


def test_tags_are_ordered_and_described() -> None:
    tags = app.openapi()["tags"]

    assert [tag["name"] for tag in tags] == [
        "health",
        "files",
        "schemas",
        "extractors",
        "providers",
        "jobs",
    ]
    assert all(tag["description"] for tag in tags)


def test_binary_download_and_common_errors_are_explicit() -> None:
    paths = app.openapi()["paths"]

    download = paths["/v1/files/{file_id}/content"]["get"]
    assert download["responses"]["200"]["content"]["application/octet-stream"]["schema"] == {
        "type": "string",
        "format": "binary",
    }
    assert "404" in download["responses"]
    assert "400" in paths["/v1/providers/{name}/models"]["get"]["responses"]
    assert "422" in paths["/v1/schemas/validate"]["post"]["responses"]


def test_main_flow_has_executable_curl_samples() -> None:
    paths = app.openapi()["paths"]
    operations = {
        "upload": paths["/v1/files"]["post"],
        "download": paths["/v1/files/{file_id}/content"]["get"],
        "create_job": paths["/v1/jobs"]["post"],
        "get_job": paths["/v1/jobs/{job_id}"]["get"],
    }

    for operation in operations.values():
        samples = operation["x-codeSamples"]
        assert len(samples) == 1
        assert samples[0]["lang"] == "bash"
        assert samples[0]["label"] == "curl"
        assert "curl --fail --silent --show-error" in samples[0]["source"]

    assert "upload=@document.pdf" in operations["upload"]["x-codeSamples"][0]["source"]
    assert "--output document.pdf" in operations["download"]["x-codeSamples"][0]["source"]
