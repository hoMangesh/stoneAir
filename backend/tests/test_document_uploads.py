import asyncio

from app.services.document_intelligence import extract_text_from_upload, extract_text_from_uploads


class _AsyncUpload:
    def __init__(self, filename: str, raw: bytes):
        self.filename = filename
        self._raw = raw
        self.seek_calls = 0

    async def read(self):
        return self._raw

    async def seek(self, offset: int):
        assert offset == 0
        self.seek_calls += 1


def test_async_upload_adapter_reads_and_rewinds_before_csv_parsing():
    upload = _AsyncUpload("bom.csv", b"Component,Material\nMain Fabric,Cotton denim\n")
    text = asyncio.run(extract_text_from_upload(upload))
    assert "Cotton denim" in text
    assert upload.seek_calls == 1


def test_async_upload_collection_preserves_all_files():
    uploads = [_AsyncUpload("one.txt", b"denim jeans"), _AsyncUpload("two.txt", b"cotton")]
    texts = asyncio.run(extract_text_from_uploads(uploads))
    assert texts == ["denim jeans\n[uploaded:one.txt]", "cotton\n[uploaded:two.txt]"]
