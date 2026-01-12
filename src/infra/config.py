import json
import os
from typing import Dict, Any

class Config:
    def __init__(self, config_path: str = "config/config.json"):
        self.config_path = config_path
        self._data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found at {self.config_path}. Please copy config.example.json to {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            return json.load(f)

    @property
    def mode(self) -> str:
        return self._data.get("mode", "paper")
    
    @property
    def scanner(self) -> Dict[str, Any]:
        return self._data.get("scanner", {})
    
    @property
    def strategy(self) -> Dict[str, Any]:
        return self._data.get("strategy", {})
    
    @property
    def risk(self) -> Dict[str, Any]:
        return self._data.get("risk", {})

    @property
    def execution(self) -> Dict[str, Any]:
        return self._data.get("execution", {})

    @property
    def price_feed(self) -> Dict[str, Any]:
        return self._data.get("price_feed", {})

    @property
    def updown_scanner(self) -> Dict[str, Any]:
        return self._data.get("updown_scanner", {})

    @property
    def arb_scanner(self) -> Dict[str, Any]:
        return self._data.get("arb_scanner", {})

def load_config() -> Config:
    return Config()
