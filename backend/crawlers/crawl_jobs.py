# crawl_jobs.py
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path to allow 'crawlers' package imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from crawlers.topcv_playwright import TopCVPlaywrightCrawler
from crawlers.vietnamworks_playwright import VietnamWorksPlaywrightCrawler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("crawler_runner")


CRAWLER_REGISTRY = {
    "topcv": TopCVPlaywrightCrawler,
    "vietnamworks": VietnamWorksPlaywrightCrawler,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Production Job Crawler Runner"
    )

    # Resolve default config path relative to this script
    default_config = Path(__file__).resolve().parent / "crawler.yaml"

    parser.add_argument(
        "--site",
        required=True,
        choices=CRAWLER_REGISTRY.keys(),
        help="Target site to crawl"
    )

    parser.add_argument(
        "--config",
        default=str(default_config),
        help="Crawler config file"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max jobs to crawl (0 = unlimited)"
    )

    parser.add_argument(
        "--debug",
        action="store_true"
    )

    return parser.parse_args()


async def main():

    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    crawler_cls = CRAWLER_REGISTRY.get(args.site)

    if not crawler_cls:
        raise ValueError(f"Unsupported site: {args.site}")

    crawler = crawler_cls(
        config_path=args.config
    )

    if args.limit > 0:
        crawler.config["limit"] = args.limit

    logger.info(f"Starting crawler: {args.site}")

    await crawler.start_supervisor()

    logger.info("Crawling finished")


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
