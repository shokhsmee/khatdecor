import logging

from psycopg2 import OperationalError, errorcodes

from odoo import models

_logger = logging.getLogger(__name__)

CONCURRENCY = {errorcodes.SERIALIZATION_FAILURE, errorcodes.DEADLOCK_DETECTED,
               errorcodes.LOCK_NOT_AVAILABLE}


class ResGroups(models.Model):
    """Keep a restart from failing the registry of one worker.

    The Access Roles app regenerates its groups form view from
    ``_register_hook`` — on every registry load, in every worker. When the
    HTTP workers and the longpolling worker come up together they all write
    the same ``ir.ui.view`` row and one of them loses with "could not
    serialize access due to concurrent update"; Odoo then abandons that
    worker's registry load and answers 404 until the next request retries
    it (seen at every restart, ~80 s of no websocket). The view the loser
    wanted to write is the one the winner just wrote, so losing costs
    nothing: swallow the concurrency error inside a savepoint.
    """

    _inherit = "res.groups"

    def _update_role_groups_view(self):
        try:
            with self.env.cr.savepoint():
                return super()._update_role_groups_view()
        except OperationalError as error:
            if error.pgcode not in CONCURRENCY:
                raise
            _logger.info("access_roles groups view: written by another worker at the "
                         "same moment, keeping theirs")
            return None
