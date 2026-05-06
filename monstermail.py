#!/usr/bin/env python3
"""
MONSTERMAIL SORTER v3.3 - FULLY FIXED
Advanced Email Provider Sorter
Coded by officialmonsterz • https://github.com/officialmonsterz

KEY FIXES:
1. DNS: Uses explicit Google DNS (8.8.8.8, 1.1.1.1) with fallback to socket-based resolution
2. SMTP: Real conversation with proper error reporting
3. Provider Classification: Decoupled from SMTP - classifies by MX + domain patterns
4. Debug Mode: Shows exactly what's happening at each step

Requirements:
pip install rich dnspython requests
"""

from typing import Dict, List, Optional, Tuple, Any
import os
import json
import re
import smtplib
import socket
import dns.resolver
import dns.exception
import email.utils
import requests
import concurrent.futures
from datetime import datetime
from pathlib import Path
import sys
import threading
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt, FloatPrompt
from rich.layout import Layout
from rich.columns import Columns
from rich import box

console = Console()

# Email regex (proven working)
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

# Provider MX patterns for classification
PROVIDER_MX_PATTERNS = {
    'google_workspace': [r'google\.com', r'googlemail\.com', r'gmail-smtp-in\.l\.google\.com'],
    'godaddy': [r'secureserver\.net', r'worldnic\.com'],
    'rackspace': [r'rackspace\.com'],
    'zoho': [r'zoho\.com', r'zohomail\.com'],
    'mimecast': [r'mimecast\.com'],
    'proofpoint': [r'proofpoint\.com'],
    'barracuda': [r'barracuda\.com'],
    'aws_ses': [r'amazonaws\.com'],
    'icloud': [r'imap\.mail\.me\.com', r'mail\.me\.com'],
}

OFFICE365_MX_PATTERNS = [
    r'protection\.outlook\.com',
    r'mail\.protection\.outlook\.com',
    r'outlook\.com'
]

# Domain-based classification (used when MX fails or as backup)
DOMAIN_PROVIDERS = {
    'gmail.com': 'google_workspace',
    'yahoo.com': 'yahoo',
    'yahoodns.net': 'yahoo',
    'hotmail.com': 'hotmail',
    'outlook.com': 'hotmail',
    'live.com': 'hotmail',
    'msn.com': 'hotmail',
    'tutamail.com': 'tuta',
    'tutanota.com': 'tuta',
    'tuta.io': 'tuta',
    'icloud.com': 'icloud',
    'me.com': 'icloud',
    'mac.com': 'icloud',
    'aol.com': 'aol',
    'zoho.com': 'zoho',
    'protonmail.com': 'proton',
    'proton.me': 'proton',
    'pm.me': 'proton',
    'yandex.com': 'yandex',
    'yandex.ru': 'yandex',
    'mail.ru': 'mailru',
    'gmx.com': 'gmx',
    'gmx.net': 'gmx',
    'outlook.co.nz': 'hotmail',
    'outlook.com.au': 'hotmail',
}


def create_config() -> None:
    """Create config.json if it doesn't exist."""
    config_path = Path('config.json')
    if not config_path.exists():
        default_config = {
            "threads": 100,
            "smtp_timeout": 5,
            "smtp_verify": False,  # SMTP verification disabled by default (port 25 blocked on most ISPs)
            "debug": False,
            "auto_open_folder": False
        }
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        console.print(f"[green]✓[/green] Created {config_path}")


def load_config() -> Dict[str, Any]:
    """Load configuration."""
    create_config()
    with open('config.json', 'r') as f:
        return json.load(f)


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration."""
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=2)


def validate_email(email: str) -> bool:
    """Validate email format using regex only."""
    email = email.strip()
    if not email:
        return False
    return bool(EMAIL_REGEX.match(email))


# Create resolver with explicit DNS servers (fixes Windows DNS issues)
def make_resolver() -> dns.resolver.Resolver:
    """Create a resolver with explicit public DNS servers."""
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = ['8.8.8.8', '1.1.1.1', '8.8.4.4']
    r.timeout = 5
    r.lifetime = 8
    return r


RESOLVER = make_resolver()


def get_mx_records(domain: str) -> List[str]:
    """Get MX records with explicit resolver and fallback to socket/nslookup."""
    # Attempt 1: dnspython with explicit DNS
    try:
        answers = RESOLVER.resolve(domain, 'MX')
        mx_list = [str(r.exchange).rstrip('.') for r in answers]
        if mx_list:
            return mx_list
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout,
            dns.exception.Timeout, dns.resolver.NoNameservers):
        pass
    except Exception as e:
        pass  # Fall through to fallback
    
    # Attempt 2: Use socket-based fallback via getaddrinfo for MX
    # (Windows can sometimes resolve via system DNS when dnspython struggles)
    try:
        import subprocess
        result = subprocess.run(
            ['nslookup', '-type=MX', domain],
            capture_output=True, text=True, timeout=10
        )
        mx_list = []
        for line in result.stdout.split('\n'):
            line = line.strip().lower()
            if 'mx preference' in line or 'mail exchanger' in line:
                # Parse: "mx preference = 10, mail exchanger = alt1.gmail-smtp-in.l.google.com"
                if '=' in line:
                    parts = line.split('=')
                    mx_host = parts[-1].strip()
                    mx_list.append(mx_host)
        if mx_list:
            return mx_list
    except Exception:
        pass
    
    return []


def classify_provider(domain: str, mx_records: List[str]) -> str:
    """Classify email provider using MX records and domain name."""
    domain_lower = domain.lower()
    mx_str = ' '.join(mx_records).lower()
    
    # 1. Check domain-based classification first (fast, works even without MX)
    for dom_pattern, provider in DOMAIN_PROVIDERS.items():
        if dom_pattern == domain_lower or domain_lower.endswith('.' + dom_pattern):
            return provider
    
    # 2. Office365 check (MX-based)
    if any(pattern in mx_str for pattern in OFFICE365_MX_PATTERNS):
        return 'office365'
    
    # 3. Google Workspace check (MX-based)
    if any(pattern in mx_str for pattern in PROVIDER_MX_PATTERNS['google_workspace']):
        return 'google_workspace'
    
    # 4. Other providers (MX-based)
    for provider, patterns in PROVIDER_MX_PATTERNS.items():
        if provider == 'google_workspace':
            continue  # already checked
        if any(pattern in mx_str for pattern in patterns):
            return provider
    
    # 5. If we have MX records but no match, it's a custom domain
    if mx_records:
        return 'custom_mx'
    
    # 6. No MX at all
    return 'no_mx'


def autodiscover_o365(domain: str) -> bool:
    """Quick check if domain uses Office365 via autodiscover DNS."""
    # No need if we already matched above, but here for completeness
    try:
        answers = RESOLVER.resolve(f'autodiscover.{domain}', 'CNAME', lifetime=5)
        for ans in answers:
            if 'autodiscover.outlook.com' in str(ans.target).lower():
                return True
    except:
        pass
    return False


def smtp_verify(email: str, mx_servers: List[str], timeout: int) -> Tuple[bool, str]:
    """
    Verify email via real SMTP conversation.
    Returns (is_valid, details_string).
    Uses HELO -> MAIL FROM -> RCPT TO sequence.
    """
    sender = 'verify@example.org'
    local_host = 'mail.example.org'
    
    for mx in mx_servers[:3]:
        for port in [25, 587, 465]:
            try:
                if port == 465:
                    server = smtplib.SMTP_SSL(mx, port, timeout=timeout)
                else:
                    server = smtplib.SMTP(mx, port, timeout=timeout)
                
                server.set_debuglevel(0)
                
                # EHLO/HELO
                code_helo, _ = server.ehlo(local_host)
                if code_helo != 250:
                    server.quit()
                    continue
                
                # STARTTLS on port 587
                if port == 587:
                    try:
                        server.starttls()
                        server.ehlo(local_host)
                    except:
                        pass
                
                # MAIL FROM
                code_mail, _ = server.mail(sender)
                if code_mail != 250:
                    server.quit()
                    continue
                
                # RCPT TO
                code_rcpt, msg_rcpt = server.rcpt(email)
                server.quit()
                
                if code_rcpt == 250:
                    return (True, f"SMTP_250:{mx}:{port}")
                else:
                    return (False, f"SMTP_{code_rcpt}:{mx}:{port}")
                
            except smtplib.SMTPConnectError:
                continue  # Try next port/MX
            except smtplib.SMTPServerDisconnected:
                continue
            except socket.timeout:
                continue
            except ConnectionRefusedError:
                continue
            except OSError as e:
                continue
            except Exception:
                continue
    
    return (False, "SMTP_UNREACHABLE")


def test_dns_resolution(domain: str) -> None:
    """Test DNS resolution and print debug info."""
    console.print(f"\n[bold yellow]🔍 DNS Debug for: {domain}[/bold yellow]")
    
    # Test 1: System nslookup
    try:
        import subprocess
        result = subprocess.run(['nslookup', '-type=MX', domain],
                              capture_output=True, text=True, timeout=10)
        console.print(f"[dim]nslookup MX:[/dim]")
        for line in result.stdout.split('\n'):
            if 'mx' in line.lower() or 'mail' in line.lower() or 'primary' in line.lower():
                console.print(f"  {line.strip()}")
        if not any('mx' in line.lower() for line in result.stdout.split('\n')):
            console.print(f"  [red]No MX records found via nslookup[/red]")
            console.print(f"  [dim]Full output:[/dim]")
            for line in result.stdout.split('\n')[:10]:
                console.print(f"  [dim]{line.strip()}[/dim]")
    except Exception as e:
        console.print(f"  [red]nslookup failed: {e}[/red]")
    
    # Test 2: dnspython
    try:
        answers = RESOLVER.resolve(domain, 'MX')
        console.print(f"[dim]dnspython MX:[/dim]")
        for r in answers:
            console.print(f"  [green]{r.exchange}[/green] (pref: {r.preference})")
    except Exception as e:
        console.print(f"  [red]dnspython failed: {e}[/red]")
    
    # Test 3: A record (basic connectivity)
    try:
        answers = RESOLVER.resolve(domain, 'A')
        ips = [str(r) for r in answers]
        console.print(f"[dim]A records:[/dim] {', '.join(ips[:3])}")
    except Exception as e:
        console.print(f"  [red]A record lookup failed: {e}[/red]")


def process_email(email: str, config: Dict[str, Any], stats: Dict[str, int]) -> Tuple[str, str, str]:
    """
    Process a single email.
    Returns: (email, classification_status, smtp_status)
    """
    email_clean = email.strip()
    
    # Step 1: Syntax validation
    if not validate_email(email_clean):
        stats['inactive'] += 1
        return (email_clean, "SYNTAX_FAIL", "N/A")
    
    domain = email_clean.split('@')[1]
    
    # Step 2: MX record lookup
    mx_records = get_mx_records(domain)
    
    # Step 3: Classify provider (this is the MAIN output)
    provider = classify_provider(domain, mx_records)
    
    # Step 4: Optional SMTP verification
    smtp_status = "N/A"
    if config.get('smtp_verify', False) and mx_records:
        is_valid, smtp_status = smtp_verify(email_clean, mx_records, config['smtp_timeout'])
        if is_valid:
            stats[provider] = stats.get(provider, 0) + 1
        else:
            stats['inactive'] = stats.get('inactive', 0) + 1
        return (email_clean, provider, smtp_status)
    
    # No SMTP verification - classify based on DNS only
    # Mark as "active" if we have MX records (domain accepts mail)
    if provider != 'no_mx':
        stats[provider] = stats.get(provider, 0) + 1
        return (email_clean, provider, "CLASSIFIED")
    else:
        stats['inactive'] = stats.get('inactive', 0) + 1
        return (email_clean, "no_mx", "NO_MX_RECORDS")


def create_output_folder() -> Path:
    """Create timestamped output folder."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = Path(f"monstermail_sorter_{timestamp}")
    folder.mkdir(exist_ok=True)
    return folder


def save_results(output_path: Path, results: Dict[str, List[str]], 
                 stats: Dict[str, int], config: Dict[str, Any],
                 raw_results: List[Tuple[str, str, str]]) -> None:
    """Save all results to files."""
    
    # Write individual provider files
    for category, emails in results.items():
        if emails:
            file_path = output_path / f"{category}.txt"
            with open(file_path, 'w') as f:
                f.write('\n'.join(emails) + '\n')
    
    # Write full detailed CSV
    csv_path = output_path / "full_results.csv"
    with open(csv_path, 'w') as f:
        f.write("Email,Provider,SMTP_Status\n")
        for email, cat, smtp in raw_results:
            f.write(f"{email},{cat},{smtp}\n")
    
    # Write REPORT
    total = sum(stats.values()) or 1
    report_lines = [
        "=" * 60,
        f"  MONSTERMAIL SORTER V3.3 - PROCESSING REPORT",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        f"  Total Emails Processed: {sum(stats.values())}",
        f"  SMTP Verification: {'ON' if config.get('smtp_verify') else 'OFF'}",
        f"  Threads: {config['threads']} | Timeout: {config['smtp_timeout']}s",
        "",
        "  PROVIDER BREAKDOWN:",
        "  " + "-" * 38,
    ]
    
    # Sort by count descending
    for provider, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            pct = (count / total) * 100
            report_lines.append(f"  {provider.upper():<25} {count:>5,} ({pct:>5.1f}%)")
    
    report_lines.extend([
        "",
        "  PROVIDER LEGEND:",
        "    google_workspace  = Gmail / Google Workspace",
        "    office365         = Microsoft Office 365 / Exchange Online",
        "    yahoo             = Yahoo Mail",
        "    hotmail           = Outlook.com / Hotmail / Live",
        "    tuta              = Tutanota (encrypted)",
        "    icloud            = Apple iCloud Mail",
        "    proton            = ProtonMail",
        "    zoho              = Zoho Mail",
        "    godaddy           = GoDaddy Email",
        "    rackspace         = Rackspace Email",
        "    mimecast          = Mimecast (security gateway)",
        "    proofpoint        = Proofpoint (security gateway)",
        "    custom_mx         = Custom domain with working MX records",
        "    no_mx             = No MX records found (doesn't receive email)",
        "    syntax_fail       = Invalid email format",
        "",
        "  NOTES:",
        "    - SMTP verification is OFF by default (port 25 blocked on many ISPs)",
        "    - Provider classification is based on MX records + domain patterns",
        "    - 'CLASSIFIED' means provider was identified from DNS only",
        "    - For full details, see full_results.csv",
        "",
        "=" * 60,
    ])
    
    report_path = output_path / "REPORT.txt"
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    
    # Process log
    log_path = output_path / "process.log"
    with open(log_path, 'w') as f:
        f.write(f"MONSTERMAIL SORTER LOG - {datetime.now().isoformat()}\n")
        f.write(f"Threads: {config['threads']}, SMTP: {config.get('smtp_verify')}\n")
        f.write(f"Total processed: {sum(stats.values())}\n")
    
    return report_path


def print_banner() -> None:
    """Print ASCII banner."""
    banner = Text("""
██╗  ██╗██╗   ██╗███████╗     ██████╗ ██╗  ██╗
██║  ██║██║   ██║██╔════╝    ██╔════╝ ██║  ██║
███████║██║   ██║█████╗      ██║  ███╗███████║
██╔══██║██║   ██║██╔══╝      ██║   ██║██╔══██║
██║  ██║╚██████╔╝███████╗    ╚██████╔╝██║  ██║
╚═╝  ╚═╝ ╚═════╝ ╚═════╝     ╚═════╝ ╚═╝  ╚═╝

Advanced Email Provider Sorter v3.3
Coded by officialmonsterz • https://github.com/officialmonsterz
    """, style="bold cyan")
    console.print(Panel(banner, border_style="bright_blue", expand=False))


def show_menu(config: Dict[str, Any]) -> str:
    """Show main menu."""
    verify_status = "ON" if config.get('smtp_verify') else "OFF"
    table = Table(show_header=False, box=None)
    table.add_row("[1] 🚀 Start Sorting")
    table.add_row("[2] ⚙️  Settings")
    table.add_row("[3] 🔍 DNS Debug Mode")
    table.add_row("[4] ℹ️  About")
    table.add_row("[5] ❌ Exit")
    table.add_row("")
    table.add_row(f"[dim]Threads: {config['threads']:,} | Timeout: {config['smtp_timeout']}s | SMTP Verify: {verify_status}[/dim]")
    
    console.print(Panel(table, title="MONSTERMAIL SORTER", border_style="cyan"))
    choice = Prompt.ask("Enter choice", choices=["1", "2", "3", "4", "5"], default="1")
    return choice


def settings_menu(config: Dict[str, Any]) -> Dict[str, Any]:
    """Settings interface."""
    console.print("\n[bold cyan]⚙️  SETTINGS[/bold cyan]")
    
    # Threads
    while True:
        try:
            t = Prompt.ask("Threads (100-5000)", default=str(config['threads']))
            config['threads'] = max(1, min(5000, int(t)))
            break
        except ValueError:
            console.print("[red]Enter a valid number[/red]")
    
    # Timeout
    while True:
        try:
            t = Prompt.ask("SMTP Timeout (1-30s)", default=str(config['smtp_timeout']))
            config['smtp_timeout'] = max(1, min(30, int(t)))
            break
        except ValueError:
            console.print("[red]Enter a valid number[/red]")
    
    # SMTP verification toggle
    config['smtp_verify'] = Confirm.ask(
        "Enable SMTP verification? (Requires port 25/587 access - often blocked by ISPs)",
        default=config.get('smtp_verify', False)
    )
    
    save_config(config)
    console.print("[green]✓ Settings saved![/green]")
    return config


def about_screen() -> None:
    """About screen."""
    info = [
        "MONSTERMAIL SORTER v3.3",
        "",
        "How it works:",
        "  1. Validates email syntax (regex)",
        "  2. Resolves MX records via DNS (Google DNS)",
        "  3. Classifies provider by MX patterns + domain",
        "  4. Optionally verifies via SMTP handshake",
        "",
        "Provider detection:",
        "  Google Workspace, Office365, Yahoo, Outlook/Hotmail,",
        "  Tutanota, iCloud, ProtonMail, Zoho, GoDaddy,",
        "  Rackspace, Mimecast, Proofpoint, AWS SES, and more",
        "",
        "⭐ https://github.com/officialmonsterz"
    ]
    console.print(Panel("\n".join(info), title="ℹ️  About", border_style="bright_blue"))
    Prompt.ask("Press Enter to return")


def debug_dns_menu() -> None:
    """Interactive DNS debug tool."""
    console.print("\n[bold cyan]🔍 DNS DEBUG MODE[/bold cyan]")
    console.print("Test MX record resolution for any domain.\n")
    
    while True:
        domain = Prompt.ask("Enter domain to test (or 'q' to quit)")
        if domain.lower() in ('q', 'quit', 'exit'):
            break
        
        if '@' in domain:
            domain = domain.split('@')[1]
        
        test_dns_resolution(domain)


def validate_input_file(file_path: str) -> Tuple[bool, str, List[str]]:
    """Validate input file."""
    path = Path(file_path)
    if not path.exists():
        return False, f"File not found: {file_path}", []
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        
        if not lines:
            return False, "File is empty", []
        
        valid = [l for l in lines if validate_email(l)]
        console.print(f"[green]✓[/green] Loaded {len(lines):,} lines ({len(valid):,} valid email format)")
        
        if not valid:
            console.print("[yellow]⚠ WARNING: No valid email addresses found.[/yellow]")
            console.print("[yellow]  Expected format: user@domain.com[/yellow]")
            if not Confirm.ask("Proceed anyway?", default=False):
                return False, "Cancelled", []
        
        return True, "", lines
    except Exception as e:
        return False, f"Error: {str(e)}", []


def main_processing(config: Dict[str, Any]) -> None:
    """Main processing pipeline."""
    console.print("\n[bold cyan]📁 INPUT FILE[/bold cyan]")
    file_path = Prompt.ask("Enter .txt file path")
    
    is_valid, error, emails = validate_input_file(file_path)
    if not is_valid:
        console.print(f"[red]{error}[/red]")
        return
    
    output_path = create_output_folder()
    
    # Initialize result containers
    results: Dict[str, List[str]] = {}
    raw_results: List[Tuple[str, str, str]] = []
    stats: Dict[str, int] = {}
    
    # Stats lock
    lock = threading.Lock()
    processed_count = [0]
    start_time = datetime.now()
    
    console.print(f"\n[bold green]🚀 Processing {len(emails):,} emails...[/bold green]")
    console.print(f"📂 Output: {output_path}")
    console.print(f"⚡ Threads: {config['threads']:,} | SMTP Verify: {'ON' if config.get('smtp_verify') else 'OFF'}")
    
    # Progress live display
    table = Table(title="Live Processing", box=box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        
        task = progress.add_task("Processing...", total=len(emails))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=config['threads']) as executor:
            # Submit all tasks
            futures = {
                executor.submit(process_email, email, config, stats): email
                for email in emails
            }
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    email, category, smtp_status = future.result()
                    
                    with lock:
                        raw_results.append((email, category, smtp_status))
                        if category not in results:
                            results[category] = []
                        results[category].append(email)
                        processed_count[0] += 1
                    
                    # Update progress
                    progress.update(
                        task,
                        advance=1,
                        description=f"[{category}] {email}"
                    )
                    
                    # Print live stats periodically
                    if processed_count[0] % 10 == 0:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        speed = processed_count[0] / max(elapsed, 1)
                        remaining = len(emails) - processed_count[0]
                        eta = remaining / max(speed, 1)
                        progress.console.print(
                            f"  [dim]✓ {processed_count[0]:,}/{len(emails):,} "
                            f"({speed:.0f}/s) ETA: {eta:.0f}s[/dim]"
                        )
                        
                except KeyboardInterrupt:
                    console.print("\n[yellow]⚠ Interrupted! Saving partial results...[/yellow]")
                    save_results(output_path, results, stats, config, raw_results)
                    return
                except Exception as e:
                    with lock:
                        processed_count[0] += 1
                    progress.update(task, advance=1)
                    continue
    
    # Complete
    duration = (datetime.now() - start_time).total_seconds()
    console.print(f"\n[bold green]✅ Complete! ({duration:.1f}s)[/bold green]")
    
    report_path = save_results(output_path, results, stats, config, raw_results)
    
    # Show summary
    console.print("\n[bold cyan]📊 SUMMARY[/bold cyan]")
    summary_table = Table(box=box.ROUNDED)
    summary_table.add_column("Provider", style="cyan")
    summary_table.add_column("Count", justify="right", style="green")
    
    for provider, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            summary_table.add_row(provider.upper(), str(count))
    
    console.print(summary_table)
    console.print(f"\n📁 [cyan]{output_path}[/cyan]")
    console.print(f"📄 [cyan]{report_path}[/cyan]")
    
    if config.get('auto_open_folder') and Confirm.ask("Open output folder?", default=True):
        try:
            os.startfile(str(output_path))
        except:
            pass


def main() -> None:
    """Entry point."""
    try:
        print_banner()
        config = load_config()
        
        while True:
            choice = show_menu(config)
            
            if choice == "1":
                main_processing(config)
            elif choice == "2":
                config = settings_menu(config)
            elif choice == "3":
                debug_dns_menu()
            elif choice == "4":
                about_screen()
            elif choice == "5":
                console.print("👋 Goodbye!")
                sys.exit(0)
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye![/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal Error: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())


if __name__ == "__main__":
    main()
