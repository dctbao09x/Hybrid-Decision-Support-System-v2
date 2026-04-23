#!/usr/bin/env python3
"""
Job Market Data Crawler Runner

Run Playwright-based crawlers for VietnamWorks and TopCV
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

from crawlers.vietnamworks_playwright import VietnamWorksPlaywrightCrawler
from crawlers.topcv_playwright import TopCVPlaywrightCrawler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('crawler.log')
    ]
)

logger = logging.getLogger(__name__)


async def run_crawler(site: str, config_path: str, max_pages: int = 5):
    """Run crawler for specified site"""
    logger.info(f"Starting crawler for {site}")

    try:
        if site == 'vietnamworks':
            crawler = VietnamWorksPlaywrightCrawler(config_path)
        elif site == 'topcv':
            crawler = TopCVPlaywrightCrawler(config_path)
        else:
            logger.error(f"Unknown site: {site}")
            return None

        results = await crawler.crawl_jobs(max_pages=max_pages)

        logger.info(f"Crawler completed for {site}:")
        logger.info(f"  - Total jobs: {results['total_jobs']}")
        logger.info(f"  - Pages processed: {results['pages_processed']}")
        logger.info(f"  - URLs processed: {results.get('urls_processed', 0)}")
        logger.info(f"  - Memory peak: {results.get('memory_peak', 0):.1f}MB")
        logger.info(f"  - Duration: {results['duration']}")
        logger.info(f"  - Errors: {len(results['errors'])}")

        if results['errors']:
            logger.warning("Errors encountered:")
            for error in results['errors'][:5]:  # Show first 5 errors
                logger.warning(f"  - {error}")

        return results

    except Exception as e:
        logger.error(f"Error running crawler for {site}: {e}")
        return None


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Job Market Data Crawler')
    parser.add_argument('--site', choices=['vietnamworks', 'topcv', 'both'],
                       default='both', help='Site to crawl')
    parser.add_argument('--config', default='config/crawler_config.yaml',
                       help='Path to config file')
    parser.add_argument('--max-pages', type=int, default=5,
                       help='Maximum pages to crawl per site')
    parser.add_argument('--install-playwright', action='store_true',
                       help='Install Playwright browsers')

    args = parser.parse_args()

    # Install Playwright if requested
    if args.install_playwright:
        logger.info("Installing Playwright browsers...")
        try:
            import subprocess
            subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
            logger.info("Playwright browsers installed successfully")
        except Exception as e:
            logger.error(f"Failed to install Playwright browsers: {e}")
            return

    # Check config file
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return

    # Run crawlers
    sites = ['vietnamworks', 'topcv'] if args.site == 'both' else [args.site]

    for site in sites:
        logger.info(f"=" * 50)
        await run_crawler(site, str(config_path), args.max_pages)
        logger.info(f"=" * 50)

    logger.info("All crawlers completed")


if __name__ == '__main__':
    asyncio.run(main())
