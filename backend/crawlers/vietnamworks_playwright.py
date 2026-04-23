"""
VietnamWorks Playwright Crawler

Crawl job listings from vietnamworks.com using Playwright
"""

import asyncio
import logging
import re
from typing import List, Optional, Dict
from urllib.parse import urljoin

from playwright.async_api import Page
from .playwright_crawler import PlaywrightCrawler

logger = logging.getLogger(__name__)


class VietnamWorksPlaywrightCrawler(PlaywrightCrawler):
    """Crawler for vietnamworks.com using Playwright"""

    def __init__(self, config_path: str):
        super().__init__(config_path, "vietnamworks")

    async def _wait_for_dynamic_content(self, page: Page):
        """Wait for VietnamWorks specific dynamic content"""
        try:
            # Wait for network idle to ensure SPA content loads
            await page.wait_for_load_state("networkidle", timeout=10000)
            
            # Wait for job listings container
            # Try generic selectors for job lists
            try:
                await page.wait_for_selector('div[class*="job-list"], div[class*="JobCard"], a[href*="-jv"]', timeout=5000)
            except Exception:
                pass  # Selector timeout is expected for some pages

        except Exception as e:
            logger.debug(f"Dynamic content wait error: {e}")

    async def extract_job_urls(self, page: Page) -> List[str]:
        """Extract job URLs from VietnamWorks listing page"""
        job_urls = []

        try:
            # Get all links on the page
            all_links = await page.query_selector_all('a')
            
            for link in all_links:
                href = await link.get_attribute('href')
                if not href:
                    continue

                # Normalize URL
                full_url = urljoin(self.site_config['base_url'], href)

                # Filter logic
                if 'vietnamworks.com' not in full_url:
                    continue
                
                if "employer.vietnamworks.com" in full_url:
                    continue

                # Check for Job URL patterns
                # Pattern 1: Ends with -jv + digits (e.g., ...-jv123456)
                # Pattern 2: Contains /viec-lam/ (e.g., /viec-lam/...)
                # Pattern 3: Contains /job/
                is_job = False
                if re.search(r'-jv\d+$', full_url):
                    is_job = True
                elif '/viec-lam/' in full_url:
                    is_job = True
                elif '/job/' in full_url:
                    is_job = True
                
                if is_job and full_url not in job_urls:
                    job_urls.append(full_url)

            logger.info(f"Extracted {len(job_urls)} job URLs from VietnamWorks")

        except Exception as e:
            logger.error(f"Error extracting job URLs: {e}")

        return job_urls

    async def extract_job_details(self, page: Page, job_url: str) -> Optional[Dict]:
        """Extract job details from VietnamWorks job page"""
        try:
            # Extract job ID from URL
            # Support both /job/123 and -jv123 formats
            job_id_match = re.search(r'(?:/job/|-jv)(\d+)', job_url)
            if not job_id_match:
                logger.warning(f"Could not extract job ID from URL: {job_url}")
                return None

            job_id = f"vw_{job_id_match.group(1)}"

            # Extract job data
            job_data = {
                'job_id': job_id,
                'url': job_url,
                'source': 'vietnamworks'
            }

            # Job title
            title_selectors = [
                'h1.job-title',
                '.job-detail-title h1',
                '[data-testid="job-title"]',
                '.job-title',
                'h1'
            ]

            for selector in title_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['job_title'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Company name
            company_selectors = [
                '.company-name',
                '.employer-name',
                '[data-testid="company-name"]',
                '.job-company-name',
                '.company-info a'
            ]

            for selector in company_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['company'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Salary
            salary_selectors = [
                '.salary',
                '.job-salary',
                '[data-testid="salary"]',
                '.salary-range'
            ]

            for selector in salary_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['salary'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Location
            location_selectors = [
                '.location',
                '.job-location',
                '[data-testid="location"]',
                '.address'
            ]

            for selector in location_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['location'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Skills
            skills_selectors = [
                '.skills',
                '.job-skills',
                '[data-testid="skills"]',
                '.skill-tags'
            ]

            skills = []
            for selector in skills_selectors:
                try:
                    elements = await page.query_selector_all(f'{selector} span, {selector} a')
                    if elements:
                        for element in elements:
                            skill = (await element.text_content()).strip()
                            if skill and skill not in skills:
                                skills.append(skill)
                        break
                except Exception:
                    continue

            job_data['skills'] = ', '.join(skills) if skills else ''

            # Experience
            experience_selectors = [
                '.experience',
                '.job-experience',
                '[data-testid="experience"]',
                '.experience-required'
            ]

            for selector in experience_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['experience'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Posted date
            date_selectors = [
                '.posted-date',
                '.job-posted-date',
                '[data-testid="posted-date"]',
                '.date-posted'
            ]

            for selector in date_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['posted_date'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            # Description (optional)
            desc_selectors = [
                '.job-description',
                '.job-detail-description',
                '[data-testid="job-description"]'
            ]

            for selector in desc_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        job_data['description'] = (await element.text_content()).strip()
                        break
                except Exception:
                    continue

            logger.debug(f"Extracted job data for {job_id}")

            return job_data

        except Exception as e:
            logger.error(f"Error extracting job details from {job_url}: {e}")
            return None

    async def get_next_page_url(self, page: Page, current_url: str, page_num: int) -> Optional[str]:
        """Get next page URL from VietnamWorks pagination"""
        try:
            # VietnamWorks pagination selectors
            next_selectors = [
                '.pagination .next',
                '.paging .next',
                'a[rel="next"]',
                '.pagination-next'
            ]

            for selector in next_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        href = await element.get_attribute('href')
                        if href:
                            return urljoin(self.site_config['base_url'], href)
                except Exception:
                    continue

            # Fallback: construct URL with page parameter
            if '?' in current_url:
                if 'page=' in current_url:
                    return current_url.replace(f'page={page_num}', f'page={page_num + 1}')
                else:
                    return f"{current_url}&page={page_num + 1}"
            else:
                return f"{current_url}?page={page_num + 1}"

        except Exception as e:
            logger.debug(f"Error getting next page URL: {e}")

        return None
