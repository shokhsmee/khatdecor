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

    # The app builds the permission part of the role form out of Odoo 18's
    # «reified» group fields. In Odoo 19 groups hang off privileges, so the
    # generated block showed nothing but a technical list in debug mode. The
    # role form now uses Odoo 19's own per-app selector, the one the user form
    # has, and this view no longer changes with the installed modules.
    ROLE_GROUPS_ARCH = (
        '<field name="groups_ids" position="attributes">'
        '<attribute name="widget">res_user_group_ids</attribute>'
        '<attribute name="nolabel">1</attribute>'
        '</field>'
    )

    def _update_role_groups_view(self):
        view = self.env.ref("access_roles.access_role_view_form_groups", raise_if_not_found=False)
        if not view or view.arch == self.ROLE_GROUPS_ARCH:
            return None
        try:
            with self.env.cr.savepoint():
                view.with_context(lang=None).write({"arch": self.ROLE_GROUPS_ARCH})
                return None
        except OperationalError as error:
            if error.pgcode not in CONCURRENCY:
                raise
            _logger.info("access_roles groups view: written by another worker at the "
                         "same moment, keeping theirs")
            return None
