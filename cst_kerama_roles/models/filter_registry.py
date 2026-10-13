import logging

from psycopg2 import OperationalError

from odoo import models

from .res_groups import CONCURRENCY

_logger = logging.getLogger(__name__)


class FilterRegistry(models.Model):
    """Stop the Access Roles filter scan from failing a worker's registry.

    Same story as [[res_groups]]: ``filter.registry._register_hook`` re-scans
    every search view and rewrites its own rows - plus the ``ir.ui.view`` rows
    behind its ``view_ids`` many2many - on every registry load, in every
    worker. Four HTTP workers coming up together fight over the same rows and
    the losers die with "could not serialize access due to concurrent update"
    or "canceling statement due to lock timeout"; Odoo then throws that
    worker's registry away and serves 404 until something retries it. This
    accounted for 83 "Failed to load registry" entries in one day's log.

    What the loser wanted to write is what the winner just wrote, so losing
    costs nothing.
    """

    _inherit = "filter.registry"

    def _register_hook(self):
        try:
            with self.env.cr.savepoint():
                return super()._register_hook()
        except OperationalError as error:
            if error.pgcode not in CONCURRENCY:
                raise
            _logger.info("access_roles filter registry: rebuilt by another worker "
                         "at the same moment, keeping theirs")
            return True
