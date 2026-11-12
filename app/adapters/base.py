from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from playwright.async_api import Page


class AdapterManualAuthRequired(Exception):
    """Raised when the target site requires manual login or user verification."""


class AdapterExecutionError(Exception):
    """Raised when automating the target site fails or times out."""


@dataclass(slots=True)
class AdapterCapabilities:
    text_to_image: bool = True
    image_edit: bool = True
    models: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=lambda: ["1024x1024"])
    max_images: int = 1


@dataclass(slots=True)
class SessionCheckResult:
    status: Literal["ready", "needs_auth", "error"]
    message: str
    url: str | None = None


@dataclass(slots=True)
class GenerationRequest:
    prompt: str
    model: str | None = None
    size: str | None = None
    n: int = 1
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EditRequest:
    prompt: str
    image_paths: list[Path] = field(default_factory=list)
    model: str | None = None
    size: str | None = None
    n: int = 1
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def image_path(self) -> Path | None:
        """First reference image (backward-compat convenience)."""
        return self.image_paths[0] if self.image_paths else None


@dataclass(slots=True)
class AdapterImageResult:
    images_bytes: list[bytes]
    raw_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SiteAdapter(ABC):
    """Contract implemented by each browser-automated image generation site."""

    name: str
    display_name: str
    home_url: str
    capabilities: AdapterCapabilities
    model_aliases: tuple[str, ...] = ()

    @abstractmethod
    async def open_for_manual_auth(self, page: Page) -> None:
        """Navigate to the site so the user can manually authenticate or accept terms."""

    @abstractmethod
    async def check_session(self, page: Page) -> SessionCheckResult:
        """Inspect the active page and report whether automation can proceed."""

    @abstractmethod
    async def generate_image(self, page: Page, req: GenerationRequest) -> AdapterImageResult:
        """Submit a text prompt and return generated image bytes."""

    @abstractmethod
    async def edit_image(self, page: Page, req: EditRequest) -> AdapterImageResult:
        """Upload an input image with a prompt and return edited image bytes."""
