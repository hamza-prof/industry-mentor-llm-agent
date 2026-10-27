import io

from tests.helpers import add_picture, make_png, new_docx

MD = b"# Intro\n\nHello.\n\n# Method\n\nWe did things.\n"


def upload(client, name="a.md", content=MD, doc_type="report"):
    return client.post(
        "/api/documents", files={"file": (name, content)}, data={"doc_type": doc_type}
    )


def docx_bytes(with_text=True) -> bytes:
    d = new_docx()
    if with_text:
        d.add_heading("Results", level=1)
        d.add_paragraph("See the chart.")
    add_picture(d.add_paragraph(), make_png())
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_upload_markdown_returns_parsed_document(client):
    r = upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0 and body["duplicate"] is False
    assert [s["heading"] for s in body["sections"]] == ["Intro", "Method"]
    assert body["filename"] == "a.md" and body["doc_type"] == "report"


def test_get_list_and_one(client):
    doc_id = upload(client).json()["id"]
    listed = client.get("/api/documents").json()
    assert [d["id"] for d in listed] == [doc_id]
    assert listed[0]["section_count"] == 2 and listed[0]["figure_count"] == 0
    assert client.get(f"/api/documents/{doc_id}").json()["sections"][1]["heading"] == "Method"


def test_unknown_document_404(client):
    r = client.get("/api/documents/999")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_too_large_413(make_client):
    with make_client(max_upload_mb=1) as c:
        r = upload(c, content=b"x" * (1024 * 1024 + 10))
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"


def test_bad_extension_415(client):
    r = upload(client, name="virus.exe", content=b"MZ...")
    assert r.status_code == 415 and r.json()["code"] == "UNSUPPORTED_FILE_TYPE"


def test_extension_content_mismatch_415(client):
    r = upload(client, name="fake.pdf", content=b"just some text")
    assert r.status_code == 415 and r.json()["code"] == "FILE_TYPE_MISMATCH"
    r = upload(client, name="fake.docx", content=b"just some text")
    assert r.json()["code"] == "FILE_TYPE_MISMATCH"
    r = upload(client, name="bin.txt", content=b"\x00\x01\x02binary")
    assert r.json()["code"] == "FILE_TYPE_MISMATCH"


def test_empty_file_422_with_code_and_detail(client):
    r = upload(client, content=b"")
    assert r.status_code == 422
    assert r.json()["code"] == "EMPTY_DOCUMENT" and r.json()["detail"]


def test_invalid_doc_type_422(client):
    assert upload(client, doc_type="essay").status_code == 422


def test_parse_error_leaves_no_files(client, tmp_path):
    upload(client, name="b.md", content=b"   \n  ")
    uploads = tmp_path / "data" / "uploads"
    assert not any(uploads.iterdir())


def test_chinese_filename_kept_and_stored_under_uuid(client, tmp_path):
    r = upload(client, name="实践报告.md")
    assert r.json()["filename"] == "实践报告.md"
    stored = [p.name for p in (tmp_path / "data" / "uploads").iterdir()]
    assert stored and all("实践" not in n for n in stored)


def test_path_traversal_filename_is_harmless(client, tmp_path):
    r = upload(client, name="../../evil.md")
    assert r.status_code == 201 and r.json()["filename"] == "evil.md"
    assert not (tmp_path / "evil.md").exists() and not (tmp_path / "data" / "evil.md").exists()


def test_duplicate_upload_returns_existing(client):
    first = upload(client).json()
    r = upload(client, name="copy.md")
    assert r.status_code == 200
    assert r.json()["id"] == first["id"] and r.json()["duplicate"] is True
    assert len(client.get("/api/documents").json()) == 1


def test_docx_figure_served_as_png(client):
    body = upload(client, name="r.docx", content=docx_bytes()).json()
    assert body["figure_count"] == 1
    fig = body["sections"][0]["paragraphs"][1]["figure"]
    r = client.get(f"/api/documents/{body['id']}/figures/{fig['image_id']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_figure_endpoint_rejects_bad_and_foreign_ids(client):
    a = upload(client, name="r.docx", content=docx_bytes()).json()
    b = upload(client).json()
    image_id = a["sections"][0]["paragraphs"][1]["figure"]["image_id"]
    assert client.get(f"/api/documents/{b['id']}/figures/{image_id}").status_code == 404
    assert client.get(f"/api/documents/{a['id']}/figures/..%2F..%2Fapp.db").status_code == 404
    assert client.get(f"/api/documents/{a['id']}/figures/{'0' * 32}").status_code == 404


def test_delete_removes_record_and_files(client, tmp_path):
    doc_id = upload(client, name="r.docx", content=docx_bytes()).json()["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert not any((tmp_path / "data" / "uploads").iterdir())
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404


def test_images_only_docx_needs_vision_model(make_client):
    content = docx_bytes(with_text=False)
    with make_client() as c:
        assert upload(c, name="i.docx", content=content).json()["code"] == "EMPTY_DOCUMENT"
    with make_client(vision_model="qwen-vl-max") as c:
        assert upload(c, name="i.docx", content=content).status_code == 201
