import logging
import json
import os
from dataclasses import asdict
from datetime import datetime

from src.infra.config import load_config
from src.infra.logger import setup_logger
from src.scanner.market_discovery import MarketDiscovery
from src.scanner.ranking import MarketRanker

# Setup logger
logger = setup_logger("scanner")

def main():
    logger.info("Starting Scanner...")
    
    try:
        config = load_config()
        
        discovery = MarketDiscovery(config._data)
        markets = discovery.fetch_markets()
        
        if not markets:
            logger.warning("No markets found matching basic criteria.")
            return

        ranker = MarketRanker(config)
        ranked_markets = ranker.rank_markets(markets)
        
        logger.info(f"Top {len(ranked_markets)} markets selected.")
        
        # Serialize to JSON
        timestamp = datetime.utcnow().isoformat()
        output_data = {
            "generated_at": timestamp,
            "markets": [asdict(m) for m in ranked_markets]
        }
        
        # Helper to serialize datetime
        def json_serial(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
            
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        output_path = os.path.join(data_dir, "watchlist.json")
        with open(output_path, "w") as f:
            json.dump(output_data, f, default=json_serial, indent=2)
            
        logger.info(f"Watchlist written to {output_path}")

    except Exception as e:
        logger.exception(f"Scanner failed: {e}")
        raise e

if __name__ == "__main__":
    main()
