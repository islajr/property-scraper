"""Install user systemd units without enabling them or starting recovery."""
import argparse
from pathlib import Path


def systemd_path(path, quoted=True):
    # Path directives consume literal paths; ExecStart/Environment use quotes.
    value = str(path.resolve())
    if '\n' in value or '\r' in value:
        raise ValueError('Paths cannot contain newlines')
    if not quoted:
        return value.replace('%', '%%')
    return value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--unit-dir', type=Path, default=Path.home()/'.config/systemd/user')
    parser.add_argument('--config-dir', type=Path, default=Path.home()/'.config/property-scraper')
    parser.add_argument('--state-dir', type=Path, default=Path.home()/'.local/state/property-scraper/rental-recovery')
    args = parser.parse_args()
    project = args.project_dir.resolve()
    if not (project/'scripts/run_rental_recovery.sh').is_file():
        parser.error('Project directory does not contain the recovery entry point')
    args.unit_dir.mkdir(parents=True, exist_ok=True)
    args.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = args.config_dir/'rental-recovery.env'
    # Preserve an operator's selected mode and limits on subsequent installs.
    if not config.exists():
        config.write_text('RENTAL_RECOVERY_MODE=preview\n'
                          'RENTAL_RECOVERY_MAX_LISTINGS=300\n'
                          'RENTAL_RECOVERY_MAX_HTTP_REQUESTS=1000\n'
                          'RENTAL_RECOVERY_MAX_SECONDS=1800\n')
        config.chmod(0o600)
    template_dir = Path(__file__).resolve().parent/'systemd'
    service = (template_dir/'scraper-rental-recovery.service.in').read_text()
    for key, path in {'PROJECT_DIR': project, 'STATE_DIR': args.state_dir,
                      'CONFIG_FILE': config}.items():
        service = service.replace('@'+key+'@', systemd_path(path))
    service = service.replace('@PROJECT_DIR_RAW@', systemd_path(project, quoted=False))
    service = service.replace('@CONFIG_FILE_RAW@', systemd_path(config, quoted=False))
    (args.unit_dir/'scraper-rental-recovery.service').write_text(service)
    (args.unit_dir/'scraper-rental-recovery.timer').write_text(
        (template_dir/'scraper-rental-recovery.timer').read_text())
    print(f'Installed units in {args.unit_dir.resolve()}')
    print(f'Mode and limits: {config.resolve()}')
    print('Nothing started or enabled. To enable:')
    print('systemctl --user daemon-reload')
    print('systemctl --user enable --now scraper-rental-recovery.timer')


if __name__ == '__main__':
    main()
