#!/usr/bin/env python3

from functools import partial
import io
import json
import re
import sys

from PyQt5.Qt import QUrl  # pylint: disable=no-name-in-module
from calibre_plugins.koreader.slpp import slpp as lua  # pylint: disable=import-error
from calibre_plugins.koreader.config import (
    COLUMNS,
    CONFIG,  # pylint: disable=import-error
)
from calibre_plugins.koreader import (
    DEBUG,
    DRY_RUN,
    PYDEVD,
    KoreaderSync,  # pylint: disable=import-error
)
from calibre.gui2.dialogs.message_box import MessageBox  # pylint: disable=no-name-in-module, disable=import-error
from calibre.gui2.actions import InterfaceAction  # pylint: disable=no-name-in-module, disable=import-error
from calibre.gui2 import (
    error_dialog,
    warning_dialog,
    info_dialog,
    open_url,  # pylint: disable=no-name-in-module, disable=import-error
)
from calibre.devices.usbms.driver import debug_print as root_debug_print  # pylint: disable=no-name-in-module, disable=import-error
from calibre.constants import numeric_version  # pylint: disable=no-name-in-module, disable=import-error

__license__ = 'GNU GPLv3'
__copyright__ = '2021, harmtemolder <mail at harmtemolder.com>'
__docformat__ = 'restructuredtext en'

if numeric_version >= (5, 5, 0):
    module_debug_print = partial(root_debug_print, ' koreader:action:', sep='')
else:
    module_debug_print = partial(root_debug_print, 'koreader:action:')

if DEBUG and PYDEVD:
    try:
        sys.path.append(
            # '/Applications/PyCharm.app/Contents/debug-eggs/pydevd-pycharm.egg'  # macOS
            '/opt/pycharm-professional/debug-eggs/pydevd-pycharm.egg'  # Manjaro Linux
        )
        import pydevd_pycharm  # pylint: disable=import-error

        pydevd_pycharm.settrace(
            'localhost', stdoutToServer=True, stderrToServer=True,
            suspend=False
        )
    except Exception as e:
        module_debug_print('could not start pydevd_pycharm, e = ', e)
        PYDEVD = False


class KoreaderAction(InterfaceAction):
    name = KoreaderSync.name
    action_spec = (name, 'copy-to-library.png', KoreaderSync.description, None)
    action_add_menu = True
    action_menu_clone_qaction = 'Sync from KOReader'
    dont_add_to = frozenset(
        [
            'context-menu', 'context-menu-device', 'toolbar-child', 'menubar',
            'menubar-device', 'context-menu-cover-browser',
            'context-menu-split']
    )
    dont_remove_from = InterfaceAction.all_locations - dont_add_to
    action_type = 'current'

    def genesis(self):
        debug_print = partial(module_debug_print, 'KoreaderAction:genesis:')
        debug_print('start')

        base = self.interface_action_base_plugin
        self.version = '{} (v{}.{}.{})'.format(base.name, *base.version)

        # Overwrite icon with actual KOReader logo
        icon = get_icons(
            'images/icon.png'
        )  # pylint: disable=undefined-variable
        self.qaction.setIcon(icon)

        # Left-click action
        self.qaction.triggered.connect(self.sync_to_calibre)

        # Right-click menu (already includes left-click action)
        self.qaction.menu().addSeparator()

        self.create_menu_action(
            self.qaction.menu(),
            'Configure KOReader Sync',
            'Configure',
            icon='config.png',
            description='Configure KOReader Sync',
            triggered=self.show_config
        )

        self.qaction.menu().addSeparator()

        self.create_menu_action(
            self.qaction.menu(),
            'Readme for KOReader Sync',
            'Readme',
            icon='dialog_question.png',
            description='About KOReader Sync',
            triggered=self.show_readme
        )

        self.create_menu_action(
            self.qaction.menu(),
            'About KOReader Sync',
            'About',
            icon='dialog_information.png',
            description='About KOReader Sync',
            triggered=self.show_about
        )

    def show_config(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_readme(self):
        debug_print = partial(module_debug_print, 'KoreaderAction:show_readme:')
        debug_print('start')
        readme_url = QUrl(
            'https://git.sr.ht/~harmtemolder/koreader-calibre'
            '-plugin#koreader-calibre-plugin'
        )
        open_url(readme_url)

    def show_about(self):
        debug_print = partial(module_debug_print, 'KoreaderAction:show_about:')
        debug_print('start')
        text = get_resources('about.txt').decode(
            'utf-8'
        )  # pylint: disable=undefined-variable
        icon = get_icons(
            'images/icon.png'
        )  # pylint: disable=undefined-variable

        about_dialog = MessageBox(
            MessageBox.INFO,
            'About {}'.format(self.version),
            text,
            det_msg='',
            q_icon=icon,
            show_copy_button=False,
            parent=None,
        )

        return about_dialog.exec_()

    def apply_settings(self):
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:apply_settings:'
        )
        debug_print('start')
        pass

    def get_connected_device(self):
        """Tries to get the connected device, if any

        :return: the connected device object or None
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:get_connected_device:'
        )

        try:
            is_device_present = self.gui.device_manager.is_device_present
        except:
            is_device_present = False

        if not is_device_present:
            debug_print('is_device_present = ', is_device_present)
            error_dialog(
                self.gui,
                'No device found',
                'No device found',
                det_msg='',
                show=True,
                show_copy_button=False
            )
            return None

        try:
            connected_device = self.gui.device_manager.connected_device
            connected_device_type = connected_device.__class__.__name__
        except:
            debug_print('could not get connected_device')
            error_dialog(
                self.gui,
                'Could not connect to device',
                'Could not connect to device',
                det_msg='',
                show=True,
                show_copy_button=False
            )
            return None

        debug_print('connected_device_type = ', connected_device_type)
        return connected_device

    def get_paths(self, device):
        """Retrieves paths to sidecars of all books in calibre's library
        on the device

        :param device: a device object
        :return: a dict of uuids with corresponding paths to sidecars
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:get_paths:'
        )

        debug_print(
            'found these paths to books:\n\t',
            '\n\t'.join([book.path for book in device.books()])
        )

        debug_print(
            'found these lpaths to books:\n\t',
            '\n\t'.join([book.lpath for book in device.books()])
        )

        paths = {
            book.uuid: re.sub(
                '\.(\w+)$', '.sdr/metadata.\\1.lua', book.path
            )
            for book in device.books()
        }

        debug_print(
            'generated {} path(s) to sidecar Lua files:\n\t'.format(
                len(paths)
            ),
            '\n\t'.join(paths.values())
        )

        return paths

    def get_sidecar(self, device, path):
        """Requests the given path from the given device and returns the
        contents of a sidecar Lua as Python dict

        :param device: a device object
        :param path: a path to a sidecar Lua on the device
        :return: dict or None
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:get_sidecar:'
        )

        with io.BytesIO() as outfile:
            try:
                device.get_file(path, outfile)
            except:
                debug_print('could not get ', path)
                return None

            contents = outfile.getvalue()

            try:
                decoded_contents = contents.decode()
            except UnicodeDecodeError:
                debug_print('could not decode ', contents)
                return None

            parsed_contents = self.parse_sidecar_lua(decoded_contents)

        return parsed_contents

    def parse_sidecar_lua(self, sidecar_lua):
        """Parses a sidecar Lua file into a Python dict

        :param sidecar_lua: the contents of a sidecar Lua as a str
        :return: a dict of those contents
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:parse_sidecar_lua:'
        )

        try:
            clean_lua = re.sub('^[^{]*', '', sidecar_lua).strip()
            decoded_lua = lua.decode(clean_lua)
        except:
            debug_print('could not decode sidecar_lua')
            decoded_lua = None

        return decoded_lua

    def update_metadata(self, uuid, keys_values_to_update):
        """Update multiple metadata columns for the given book.

        :param uuid: identifier for the book
        :param keys_values_to_update: a dict of keys to update with values
        :return: a dict of values that can be used to report back to the user
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:update_metadata:'
        )

        try:
            db = self.gui.current_db.new_api
            book_id = db.lookup_by_uuid(uuid)
        except:
            book_id = None

        if not book_id:
            debug_print('could not find {} in calibre???s library'.format(uuid))
            return False, {'result': 'could not find uuid in calibre???s library'}

        # Get the current metadata for the book from the library
        metadata = db.get_metadata(book_id)

        updates = []
        # Update that metadata locally
        for key, new_value in keys_values_to_update.items():
            if new_value != metadata.get(key):
                updates.append(key)
                metadata.set(key, new_value)

        # Write the updated metadata back to the library
        if len(updates) == 0:
            debug_print(
                'no changed metadata for uuid = ', uuid,
                ', id = ', book_id
            )
        elif DEBUG and DRY_RUN:
            debug_print(
                'would have updated the following fields for uuid = ',
                uuid, ', id = ', book_id, ': ', updates
            )
        else:
            db.set_metadata(
                book_id, metadata, set_title=False,
                set_authors=False
            )
            debug_print(
                'updated the following fields for uuid = ', uuid,
                ', id = ', book_id, ': ', updates
            )

        return True, {
            'result': 'success',
            'book_id': book_id,
        }

    def sync_to_calibre(self):
        """This plugin???s main purpose. It syncs the contents of
        KOReader???s metadata sidecar files into calibre???s metadata.

        :return:
        """
        debug_print = partial(
            module_debug_print,
            'KoreaderAction:sync_to_calibre:'
        )

        supported_devices = [
            'FOLDER_DEVICE',
            'KINDLE2',
            'KOBO',
            'KOBOTOUCH',
            'KOBOTOUCHEXTENDED',
            'POCKETBOOK622',
            'POCKETBOOK626',
            'SMART_DEVICE_APP',
            'TOLINO',
            'USER_DEFINED',
            'POCKETBOOK632',
        ]
        unsupported_devices = [
            'MTP_DEVICE',
        ]
        device = self.get_connected_device()

        if not device:
            return None

        device_class = device.__class__.__name__

        if device_class in unsupported_devices:
            debug_print('unsupported device, device_class = ', device_class)
            error_dialog(
                self.gui,
                'Device not supported',
                'Devices of the type {} are not supported by this plugin. I '
                'have tried to get it working, but couldn???t. Sorry.'.format(
                    device_class
                ),
                det_msg='',
                show=True,
                show_copy_button=False
            )
            return None
        elif device_class not in supported_devices:
            debug_print(
                'not yet supported device, device_class = ',
                device_class
            )
            warning_dialog(
                self.gui,
                'Device not yet supported',
                'Devices of the type {} are not yet supported by this plugin. '
                'Please check if there already is a feature request for this '
                '<a href="https://todo.sr.ht/~harmtemolder/koreader-calibre'
                '-plugin">here</a>. If not, feel free to create '
                'one. I\'ll try to sync anyway.'.format(device_class),
                det_msg='',
                show=True,
                show_copy_button=False
            )

        sidecar_paths = self.get_paths(device)

        results = []
        num_success = 0
        num_fail = 0

        for book_uuid, sidecar_path in sidecar_paths.items():
            sidecar_contents = self.get_sidecar(device, sidecar_path)

            if not sidecar_contents:
                debug_print('skipping uuid = ', book_uuid)
                results.append(
                    {
                        'result': 'could not get sidecar contents',
                        'book_uuid': book_uuid,
                        'sidecar_path': sidecar_path,
                    }
                )
                num_fail += 1
                continue

            keys_values_to_update = {}

            for column in COLUMNS:
                name = column['name']
                target = CONFIG[name]

                if target == '':
                    # No column mapped, so do not sync
                    continue

                property = column['sidecar_property']
                value = sidecar_contents

                for subproperty in property:
                    if subproperty in value:
                        value = value[subproperty]
                    else:
                        debug_print(
                            'subproperty "{}" not found in value'.format(
                                subproperty
                            )
                        )
                        value = None
                        break

                if not value:
                    continue

                # Transform value if required
                if 'transform' in column:
                    value = column['transform'](value)

                keys_values_to_update[target] = value

            success, result = self.update_metadata(
                book_uuid, keys_values_to_update
            )
            results.append(
                {
                    **result,
                    'book_uuid': book_uuid,
                    'sidecar_path': sidecar_path,
                    'updated': keys_values_to_update,
                }
            )
            if success:
                num_success += 1
            else:
                num_fail += 1

        if num_success > 0 and num_fail > 0:
            warning_dialog(
                self.gui,
                'Metadata for some books could not be synced',
                'Metadata was synced successfully for {}, but failed for {}. '
                'This might just be because you have not opened every book in '
                'KOReader yet. See below for details.'.format(
                    '{} book{}'.format(
                        num_success, 's' if num_success > 1 else ''
                    ),
                    '{} other{}'.format(
                        num_fail, 's' if num_fail > 1 else ''
                    )
                ),
                det_msg=json.dumps(results, indent=2),
                show=True,
                show_copy_button=False
            )
        elif num_success > 0:  # and num_fail == 0
            info_dialog(
                self.gui,
                'Metadata synced for all books',
                'Metadata synced for {}. See below for details.'.format(
                    '{} book{}'.format(
                        num_success, 's' if num_success > 1 else ''
                    )
                ),
                det_msg=json.dumps(results, indent=2),
                show=True,
                show_copy_button=False
            )
        else:  # not num_success
            error_dialog(
                self.gui,
                'No metadata could be synced',
                'No metadata could be synced. See below for details.',
                det_msg=json.dumps(results, indent=2),
                show=True,
                show_copy_button=False
            )
