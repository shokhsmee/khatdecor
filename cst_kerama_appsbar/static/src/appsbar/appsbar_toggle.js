import { _t } from '@web/core/l10n/translation';
import { patch } from '@web/core/utils/patch';
import { useService } from '@web/core/utils/hooks';
import { user } from '@web/core/user';
import { useState } from '@odoo/owl';

import { AppsBar } from '@muk_web_appsbar/webclient/appsbar/appsbar';

const LARGE = 'mk_sidebar_type_large';
const SMALL = 'mk_sidebar_type_small';

patch(AppsBar.prototype, {
    setup() {
        super.setup();
        this.orm = useService('orm');
        const cls = document.body.classList;
        this.toggleState = useState({
            enabled: cls.contains(LARGE) || cls.contains(SMALL),
            collapsed: cls.contains(SMALL),
        });
    },
    get toggleTitle() {
        return this.toggleState.collapsed ? _t('Expand') : _t('Collapse');
    },
    async _onToggleClick() {
        const collapsed = !this.toggleState.collapsed;
        this.toggleState.collapsed = collapsed;
        document.body.classList.toggle(SMALL, collapsed);
        document.body.classList.toggle(LARGE, !collapsed);
        await this.orm.write('res.users', [user.userId], {
            sidebar_type: collapsed ? 'small' : 'large',
        });
    },
});
