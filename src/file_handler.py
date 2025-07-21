import os
import json
import aiofiles
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class FileHandler:
    def __init__(self, allowed_dirs: List[str], read_only: bool = False, max_file_size_mb: int = 10):
        self.allowed_dirs = [Path(d).resolve() for d in allowed_dirs]
        self.read_only = read_only
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        
    def _validate_path(self, path: str) -> Path:
        """Validate that the path is within allowed directories."""
        target_path = Path(path).resolve()
        
        # Check if path is within any allowed directory
        for allowed_dir in self.allowed_dirs:
            try:
                target_path.relative_to(allowed_dir)
                return target_path
            except ValueError:
                continue
        
        raise ValueError(f"Path {path} is not within allowed directories")
    
    async def list_directory(self, path: str) -> List[Dict[str, Any]]:
        """List contents of a directory."""
        dir_path = self._validate_path(path)
        
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not dir_path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        items = []
        for item in dir_path.iterdir():
            try:
                stat = item.stat()
                items.append({
                    "name": item.name,
                    "path": str(item),
                    "type": "directory" if item.is_dir() else "file",
                    "size": stat.st_size if item.is_file() else None,
                    "modified": stat.st_mtime
                })
            except Exception as e:
                logger.warning(f"Error reading {item}: {e}")
                
        return sorted(items, key=lambda x: (x["type"] != "directory", x["name"]))
    
    async def read_file(self, path: str) -> str:
        """Read contents of a file."""
        file_path = self._validate_path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        
        # Check file size
        if file_path.stat().st_size > self.max_file_size_bytes:
            raise ValueError(f"File too large. Maximum size: {self.max_file_size_bytes} bytes")
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        except UnicodeDecodeError:
            # Try reading as binary if text fails
            async with aiofiles.open(file_path, 'rb') as f:
                content = await f.read()
                return f"[Binary file, {len(content)} bytes]"
    
    async def write_file(self, path: str, content: str) -> None:
        """Write content to a file."""
        if self.read_only:
            raise PermissionError("Operation not allowed in read-only mode")
        
        file_path = self._validate_path(path)
        
        # Check content size
        if len(content.encode('utf-8')) > self.max_file_size_bytes:
            raise ValueError(f"Content too large. Maximum size: {self.max_file_size_bytes} bytes")
        
        # Create parent directory if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(content)
        
        logger.info(f"File written: {file_path}")
    
    async def create_directory(self, path: str) -> None:
        """Create a new directory."""
        if self.read_only:
            raise PermissionError("Operation not allowed in read-only mode")
        
        dir_path = self._validate_path(path)
        
        if dir_path.exists():
            raise FileExistsError(f"Path already exists: {path}")
        
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Directory created: {dir_path}")
    
    async def delete_path(self, path: str) -> None:
        """Delete a file or directory."""
        if self.read_only:
            raise PermissionError("Operation not allowed in read-only mode")
        
        target_path = self._validate_path(path)
        
        if not target_path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        if target_path.is_file():
            target_path.unlink()
            logger.info(f"File deleted: {target_path}")
        elif target_path.is_dir():
            # Check if directory is empty
            if any(target_path.iterdir()):
                raise ValueError("Cannot delete non-empty directory")
            target_path.rmdir()
            logger.info(f"Directory deleted: {target_path}")
    
    async def search_files(self, path: str, pattern: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Search for files containing a pattern."""
        search_path = self._validate_path(path)
        
        if not search_path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        results = []
        pattern_lower = pattern.lower()
        
        async def search_file(file_path: Path) -> Optional[Dict[str, Any]]:
            try:
                # Skip large files
                if file_path.stat().st_size > self.max_file_size_bytes:
                    return None
                
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if pattern_lower in content.lower():
                        # Find line numbers containing the pattern
                        lines = content.splitlines()
                        matches = []
                        for i, line in enumerate(lines, 1):
                            if pattern_lower in line.lower():
                                matches.append({
                                    "line": i,
                                    "text": line.strip()[:100]  # First 100 chars
                                })
                                if len(matches) >= 5:  # Limit matches per file
                                    break
                        
                        return {
                            "path": str(file_path),
                            "matches": matches
                        }
            except Exception as e:
                logger.debug(f"Error searching {file_path}: {e}")
                return None
        
        # Recursively search files
        files_to_search = []
        for root, dirs, files in os.walk(search_path):
            for file in files:
                file_path = Path(root) / file
                files_to_search.append(file_path)
                if len(files_to_search) >= max_results * 2:  # Search more files than results
                    break
        
        # Search files concurrently
        tasks = [search_file(f) for f in files_to_search[:max_results * 2]]
        search_results = await asyncio.gather(*tasks)
        
        # Filter out None results and limit
        results = [r for r in search_results if r is not None][:max_results]
        
        return results