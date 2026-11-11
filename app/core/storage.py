import base64
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000

ALLOWED_FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}

EXTENSION_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@dataclass(slots=True)
class StoredImage:
    filename: str
    path: Path
    mime_type: str
    width: int
    height: int
    size_bytes: int


class ImageStorage:
    """Validates, normalizes, and stores uploaded source images and generated outputs."""

    def __init__(self, uploads_dir: Path, outputs_dir: Path, max_upload_bytes: int = 20 * 1024 * 1024) -> None:
        self.uploads_dir = uploads_dir.resolve()
        self.outputs_dir = outputs_dir.resolve()
        self.max_upload_bytes = max_upload_bytes
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def _validate_and_normalize(self, raw_bytes: bytes) -> tuple[bytes, str, str, int, int]:
        if len(raw_bytes) > self.max_upload_bytes:
            raise ValueError(f"Image exceeds max size of {self.max_upload_bytes // (1024 * 1024)} MB")
        try:
            with Image.open(io.BytesIO(raw_bytes)) as img:
                img.verify()
            with Image.open(io.BytesIO(raw_bytes)) as img:
                fmt = (img.format or "").upper()
                width, height = img.size
                if fmt in ALLOWED_FORMATS:
                    ext, mime = ALLOWED_FORMATS[fmt]
                    return raw_bytes, ext, mime, width, height
                # Convert non-web formats (e.g. BMP, TIFF, GIF) to real PNG bytes matching the .png extension.
                converted = img.convert("RGBA" if "A" in img.getbands() else "RGB")
                buf = io.BytesIO()
                converted.save(buf, format="PNG")
                return buf.getvalue(), "png", "image/png", width, height
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise ValueError(f"Invalid or unsupported image payload: {exc}") from exc

    def save_upload(self, raw_bytes: bytes, prefix: str = "upload") -> StoredImage:
        normalized_bytes, ext, mime, width, height = self._validate_and_normalize(raw_bytes)
        filename = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
        target = self.resolve_safe(self.uploads_dir, filename)
        target.write_bytes(normalized_bytes)
        return StoredImage(
            filename=filename,
            path=target,
            mime_type=mime,
            width=width,
            height=height,
            size_bytes=len(normalized_bytes),
        )

    def save_output(self, raw_bytes: bytes, job_id: str, index: int = 0) -> StoredImage:
        normalized_bytes, ext, mime, width, height = self._validate_and_normalize(raw_bytes)
        filename = f"{job_id}_{index}.{ext}"
        target = self.resolve_safe(self.outputs_dir, filename)
        target.write_bytes(normalized_bytes)
        return StoredImage(
            filename=filename,
            path=target,
            mime_type=mime,
            width=width,
            height=height,
            size_bytes=len(normalized_bytes),
        )

    def resolve_safe(self, base_dir: Path, filename: str) -> Path:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError("Unsafe filename")
        resolved = (base_dir / filename).resolve()
        if resolved.parent != base_dir:
            raise ValueError("Path escapes storage root")
        return resolved

    def media_type_for_path(self, path: Path) -> str:
        return EXTENSION_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")

    def get_output_path(self, filename: str) -> Path:
        path = self.resolve_safe(self.outputs_dir, filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def get_upload_path(self, filename: str) -> Path:
        path = self.resolve_safe(self.uploads_dir, filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def read_output_b64(self, filename: str) -> str:
        path = self.get_output_path(filename)
        return base64.b64encode(path.read_bytes()).decode("ascii")
