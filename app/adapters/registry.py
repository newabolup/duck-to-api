from app.adapters.base import SiteAdapter


class AdapterRegistry:
    """Stores site adapters and resolves OpenAI-style model names to an adapter."""

    def __init__(self, default_adapter: str = "duck-ai") -> None:
        self._adapters: dict[str, SiteAdapter] = {}
        self._aliases: dict[str, str] = {}
        self._default_adapter = default_adapter

    def register(self, adapter: SiteAdapter) -> None:
        key = adapter.name.lower()
        self._adapters[key] = adapter
        self._aliases[key] = key
        for alias in adapter.model_aliases:
            self._aliases[alias.lower()] = key

    def get(self, name_or_model: str | None = None) -> SiteAdapter:
        if not name_or_model:
            key = self._default_adapter.lower()
        else:
            candidate = name_or_model.strip().lower()
            key = self._aliases.get(candidate, candidate)
        adapter = self._adapters.get(key)
        if not adapter:
            available = ", ".join(sorted(self._adapters.keys()))
            raise KeyError(f"Unknown adapter or model '{name_or_model}'. Available: {available}")
        return adapter

    def list_adapters(self) -> list[dict]:
        result = []
        for adapter in self._adapters.values():
            result.append({
                "name": adapter.name,
                "display_name": adapter.display_name,
                "home_url": adapter.home_url,
                "is_default": adapter.name.lower() == self._default_adapter.lower(),
                "model_aliases": list(adapter.model_aliases),
                "capabilities": {
                    "text_to_image": adapter.capabilities.text_to_image,
                    "image_edit": adapter.capabilities.image_edit,
                    "models": adapter.capabilities.models,
                    "sizes": adapter.capabilities.sizes,
                    "max_images": adapter.capabilities.max_images,
                },
            })
        return result
