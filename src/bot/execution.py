from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class Order:
    id: str
    token_id: str
    side: str # BUY / SELL
    price: float
    size: float
    timestamp: float
    status: str = "OPEN" # OPEN, FILLED, CANCELED

class Executor(ABC):
    @abstractmethod
    def place_order(self, token_id: str, side: str, price: float, size: float) -> Optional[Order]:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        pass
    
    @abstractmethod
    def cancel_all(self, token_id: str):
        pass

    @abstractmethod
    def get_open_orders(self, token_id: str) -> List[Order]:
        pass
