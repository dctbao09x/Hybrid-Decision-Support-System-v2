import abc
import asyncio
import csv
import json
import logging
import os
import signal
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import psutil
import yaml


class BaseCrawler(abc.ABC):

    def __init__(self, config_path: str) -> None:

        self.config_path = config_path
        self.config: Dict[str, Any] = {}

        self.logger: Optional[logging.Logger] = None
        self.error_logger: Optional[logging.Logger] = None

        self.state: Dict[str, Any] = {}
        self.seen_ids: Set[str] = set()

        self.crawler_name: str = self.__class__.__name__.lower()

        self._shutdown_event = asyncio.Event()
        self._browser_lock = asyncio.Lock()

        self._supervisor_retries = 0
        self._watchdog_started = False  # FIX

        self.setup_logger()
        self.load_config()
        self.load_state()

        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    # ==================================================
    # ABSTRACT
    # ==================================================

    @abc.abstractmethod
    async def run(self) -> None:
        pass

    @abc.abstractmethod
    async def start(self) -> None:
        pass

    @abc.abstractmethod
    async def stop(self) -> None:
        pass

    # ==================================================
    # SUPERVISOR
    # ==================================================

    async def start_supervisor(self):

        max_restart = self.config.get("max_restart", 5)

        while not self._shutdown_event.is_set():

            try:

                await self.start()
                await self._start_watchdog()

                await self.run()

                break

            except Exception as e:

                self._supervisor_retries += 1

                self.error_logger.error(f"Supervisor crash: {e}")

                await self._restart_browser()

                if self._supervisor_retries >= max_restart:
                    self.error_logger.critical("Max restart reached")
                    break

                await asyncio.sleep(5)

        await self.stop()

    # ==================================================
    # PLAYWRIGHT CORE
    # ==================================================

    async def _restart_browser(self):

        self.logger.warning("Restarting crawler backend")

        await self.stop()
        await asyncio.sleep(3)
        await self.start()

    async def _ensure_browser_alive(self):
        """Override in subclass if needed"""
        pass

    # ==================================================
    # WATCHDOG
    # ==================================================

    async def _start_watchdog(self):

        # FIX: Prevent duplicate watchdog
        if self._watchdog_started:
            return

        self._watchdog_started = True

        asyncio.create_task(self._memory_watchdog())
        asyncio.create_task(self._browser_watchdog())

    async def _memory_watchdog(self):

        limit = self.config.get("max_memory_mb", 1500)

        proc = psutil.Process(os.getpid())

        while not self._shutdown_event.is_set():

            mem = proc.memory_info().rss / 1024 / 1024

            if mem > limit:
                self.error_logger.critical(
                    f"Memory overflow: {mem:.1f}MB"
                )
                await self._restart_browser()

            await asyncio.sleep(30)

    async def _browser_watchdog(self):

        while not self._shutdown_event.is_set():

            try:
                await self._ensure_browser_alive()
            except Exception as e:
                self.error_logger.error(f"Watchdog error: {e}")

            await asyncio.sleep(15)

    # ==================================================
    # CONFIG
    # ==================================================

    def load_config(self):

        config_file = Path(self.config_path)

        if not config_file.exists():
            raise FileNotFoundError(self.config_path)

        with open(config_file, "r", encoding="utf-8") as f:

            if config_file.suffix in [".yaml", ".yml"]:
                self.config = yaml.safe_load(f)

            elif config_file.suffix == ".json":
                self.config = json.load(f)

            else:
                raise ValueError("Invalid config format")

        self.logger.info("Config loaded")

    # ==================================================
    # LOGGER
    # ==================================================

    def setup_logger(self):

        logs_dir = Path("backend/crawlers/logs")
        logs_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(f"{self.crawler_name}_main")

        if not self.logger.handlers:

            self.logger.setLevel(logging.INFO)
            self.logger.propagate = True

            h = logging.FileHandler(
                logs_dir / f"{self.crawler_name}.log"
            )

            h.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(message)s"
                )
            )

            self.logger.addHandler(h)

        self.error_logger = logging.getLogger(
            f"{self.crawler_name}_err"
        )

        if not self.error_logger.handlers:

            self.error_logger.setLevel(logging.ERROR)
            self.error_logger.propagate = True

            h = logging.FileHandler(
                logs_dir / f"{self.crawler_name}_error.log"
            )

            h.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(message)s"
                )
            )

            self.error_logger.addHandler(h)

    # ==================================================
    # STATE
    # ==================================================

    def load_state(self):

        state_file = Path(
            f"data/market/state/{self.crawler_name}.json"
        )

        if state_file.exists():

            with open(state_file, "r", encoding="utf-8") as f:
                self.state = json.load(f)
                self.seen_ids = set(
                    self.state.get("seen_ids", [])
                )

        else:

            self.state = {
                "last_page": 0,
                "last_job_id": None,
                "last_run": None,
                "seen_ids": [],
            }

            self.seen_ids = set()

    def save_state(self):

        state_file = Path(
            f"data/market/state/{self.crawler_name}.json"
        )

        state_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.state["seen_ids"] = list(self.seen_ids)
        self.state["last_run"] = datetime.now().isoformat()

        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    # ==================================================
    # STORAGE
    # ==================================================

    def save_csv(self, rows: List[Dict[str, Any]], filename: str):

        if not rows:
            return

        out = []

        for r in rows:

            jid = r.get("job_id")

            if jid and jid not in self.seen_ids:
                self.seen_ids.add(jid)
                out.append(r)

        if not out:
            return

        base = Path(
            f"data/market/raw/"
            f"{datetime.now().strftime('%Y_%m')}/"
            f"{self.config.get('site','unknown')}/csv"
        )

        base.mkdir(parents=True, exist_ok=True)

        path = base / filename

        exists = path.exists()

        with open(path, "a", newline="", encoding="utf-8") as f:

            writer = csv.DictWriter(
                f,
                fieldnames=out[0].keys()
            )

            if not exists:
                writer.writeheader()

            writer.writerows(out)

    # ==================================================
    # RETRY
    # ==================================================

    async def retry_async(
        self, func, *args, max_retry=3, backoff=2.0, **kwargs
    ):

        last = None

        for i in range(max_retry + 1):

            if self._shutdown_event.is_set():
                raise asyncio.CancelledError()

            try:
                return await func(*args, **kwargs)

            except asyncio.CancelledError:
                raise

            except Exception as e:

                last = e

                if i < max_retry:

                    wait = backoff ** i

                    self.logger.warning(
                        f"Retry {i+1}/{max_retry} "
                        f"{func.__name__}: {e}"
                    )

                    await asyncio.sleep(wait)

                else:

                    self.error_logger.error(
                        f"Retry failed: {e}"
                    )

        raise last

    # ==================================================
    # TOOLS
    # ==================================================

    @contextmanager
    def timing_context(self, name: str):

        start = time.time()
        mem0 = psutil.Process().memory_info().rss / 1024 / 1024

        try:
            yield

        finally:

            end = time.time()
            mem1 = psutil.Process().memory_info().rss / 1024 / 1024

            self.logger.info(
                f"{name} | {end-start:.2f}s "
                f"| Δmem {mem1-mem0:.2f}MB"
            )

    # ==================================================
    # CLEANUP
    # ==================================================

    def _kill_zombie_chromium(self):
        """Override in subclass if needed"""
        pass

    # ==================================================
    # SHUTDOWN
    # ==================================================

    def _shutdown_handler(self, signum, frame):

        self.logger.warning(f"Signal {signum} received")

        self._shutdown_event.set()

        # FIX: Safe scheduling
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._shutdown_async())
        except RuntimeError:
            pass

    async def _shutdown_async(self):

        try:

            self.save_state()
            await self.stop()

        except Exception as e:
            self.error_logger.error(f"Shutdown error: {e}")
