"""Error types for the memory system."""


class MemoryStoreError(Exception):
    """Base exception for memory store operations."""

    def __init__(self, message: str, store_type: str = "unknown"):
        self.store_type = store_type
        super().__init__(f"[{store_type}] {message}")


class EntityNotFoundError(MemoryStoreError):
    """Raised when an entity is not found in the store."""

    def __init__(self, entity_id: str, store_type: str = "unknown"):
        self.entity_id = entity_id
        super().__init__(f"Entity not found: {entity_id}", store_type)


class StoreConnectionError(MemoryStoreError):
    """Raised when a store connection fails."""

    def __init__(self, message: str, store_type: str = "unknown"):
        super().__init__(f"Connection error: {message}", store_type)


class ValidationError(MemoryStoreError):
    """Raised when data validation fails."""

    def __init__(self, message: str, store_type: str = "unknown"):
        super().__init__(f"Validation error: {message}", store_type)
