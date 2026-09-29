export const DESKTOP_PROVISIONING_OS_ENVIRONMENT_NAMES = Object.freeze([
  '__CF_USER_TEXT_ENCODING',
  'APPDATA',
  'COMSPEC',
  'DBUS_SESSION_BUS_ADDRESS',
  'DISPLAY',
  'GNOME_KEYRING_CONTROL',
  'HOME',
  'HOMEDRIVE',
  'HOMEPATH',
  'LANG',
  'LANGUAGE',
  'LC_ALL',
  'LC_CTYPE',
  'LC_MESSAGES',
  'LOCALAPPDATA',
  'LOGNAME',
  'PATH',
  'PATHEXT',
  'PROGRAMDATA',
  'SHELL',
  'SYSTEMDRIVE',
  'SYSTEMROOT',
  'TEMP',
  'TMP',
  'TMPDIR',
  'USER',
  'USERNAME',
  'USERPROFILE',
  'WAYLAND_DISPLAY',
  'WINDIR',
  'XAUTHORITY',
  'XDG_CACHE_HOME',
  'XDG_CONFIG_HOME',
  'XDG_CURRENT_DESKTOP',
  'XDG_DATA_HOME',
  'XDG_RUNTIME_DIR',
]);

export function createDesktopProvisioningChildEnvironment(source, { platformOrigin, desktopToken, model }) {
  const environment = {};
  for (const name of DESKTOP_PROVISIONING_OS_ENVIRONMENT_NAMES) {
    const value = source[name];
    if (typeof value === 'string' && value) environment[name] = value;
  }
  environment.WORKDUDE_PLATFORM_ORIGIN = platformOrigin;
  environment.WORKDUDE_PLATFORM_ACCESS_TOKEN = desktopToken;
  environment.WORKDUDE_AI_GATEWAY_MODEL = model;
  return environment;
}
