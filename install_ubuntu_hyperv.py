#!/usr/bin/env python3

import subprocess
import sys
import os
import argparse
import time

def run_command(cmd, check=True):
    """Execute PowerShell command and return result"""
    try:
        if isinstance(cmd, list):
            cmd_str = ' '.join(cmd)
        else:
            cmd_str = cmd

        result = subprocess.run(
            ['powershell', '-Command', cmd_str],
            capture_output=True,
            text=True,
            check=check
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout, e.stderr

def check_admin():
    """Check if script is running as administrator"""
    print("[1/6] Checking administrator privileges...")
    success, stdout, _ = run_command(
        "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
    )

    if not success or "False" in stdout:
        print("ERROR: This script must be run as Administrator")
        print("Right-click PowerShell or Command Prompt and select 'Run as Administrator'")
        sys.exit(1)

    print("Running with administrator privileges")

def check_hyperv():
    """Check if Hyper-V is enabled"""
    print("\n[2/6] Checking Hyper-V status...")
    success, stdout, _ = run_command(
        "Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All | Select-Object -ExpandProperty State",
        check=False
    )

    if not success or "Enabled" not in stdout:
        print("Hyper-V is not enabled. Enabling Hyper-V...")
        print("This will require a system restart.")

        response = input("Do you want to enable Hyper-V now? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Hyper-V is required. Exiting.")
            sys.exit(1)

        run_command("Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -NoRestart")
        print("\nHyper-V has been enabled.")
        print("Please restart your computer and run this script again.")
        sys.exit(0)

    print("Hyper-V is enabled")

def download_ubuntu_iso(iso_path):
    """Check Ubuntu ISO"""
    print("\n[3/6] Checking Ubuntu ISO...")

    if os.path.exists(iso_path):
        print(f"ISO found: {iso_path}")
        return os.path.abspath(iso_path)

    print("Ubuntu 24.04 ISO not found.")
    print("\nPlease download Ubuntu 24.04 ISO manually from:")
    print("  https://ubuntu.com/download/server")
    print("  https://releases.ubuntu.com/24.04/")
    print(f"\nThen run this script again with: --iso-path <path-to-iso>")
    sys.exit(1)

def create_vm(vm_name, memory_gb, cpu_count, disk_size_gb, vm_path):
    """Create Hyper-V VM"""
    print(f"\n[4/6] Creating VM: {vm_name}...")

    # Check if VM exists
    success, stdout, _ = run_command(f'Get-VM -Name "{vm_name}"', check=False)
    if success and vm_name in stdout:
        print(f"VM '{vm_name}' already exists. Removing it...")
        run_command(f'Stop-VM -Name "{vm_name}" -Force -TurnOff', check=False)
        time.sleep(2)
        run_command(f'Remove-VM -Name "{vm_name}" -Force', check=False)
        time.sleep(2)

    # Create VM directory
    vm_dir = os.path.join(vm_path, vm_name)
    os.makedirs(vm_dir, exist_ok=True)

    # Create new VM
    memory_bytes = memory_gb * 1024 * 1024 * 1024
    cmd = f'New-VM -Name "{vm_name}" -MemoryStartupBytes {memory_bytes} -Generation 2 -Path "{vm_path}"'
    run_command(cmd)

    # Configure VM
    run_command(f'Set-VM -Name "{vm_name}" -ProcessorCount {cpu_count} -AutomaticStartAction Start -AutomaticStartDelay 10')
    run_command(f'Set-VM -Name "{vm_name}" -CheckpointType Disabled')

    # Enable nested virtualization (optional, for running containers)
    run_command(f'Set-VMProcessor -VMName "{vm_name}" -ExposeVirtualizationExtensions $true', check=False)

    print(f"VM created with {memory_gb}GB RAM, {cpu_count} CPUs")

def create_storage(vm_name, disk_size_gb, iso_path, vm_path):
    """Create and attach virtual disk and ISO"""
    print(f"\n[5/6] Creating storage...")

    # Create virtual hard disk
    vm_dir = os.path.join(vm_path, vm_name)
    vhdx_path = os.path.join(vm_dir, "Virtual Hard Disks", f"{vm_name}.vhdx")

    os.makedirs(os.path.dirname(vhdx_path), exist_ok=True)

    disk_size_bytes = disk_size_gb * 1024 * 1024 * 1024
    cmd = f'New-VHD -Path "{vhdx_path}" -SizeBytes {disk_size_bytes} -Dynamic'
    run_command(cmd)

    # Add SCSI controller and attach disk
    run_command(f'Add-VMScsiController -VMName "{vm_name}"', check=False)
    run_command(f'Add-VMHardDiskDrive -VMName "{vm_name}" -Path "{vhdx_path}"')

    # Add DVD drive and attach ISO
    run_command(f'Add-VMDvdDrive -VMName "{vm_name}" -Path "{iso_path}"')

    # Set boot order (DVD first, then hard disk)
    run_command(f'$dvd = Get-VMDvdDrive -VMName "{vm_name}"; $hdd = Get-VMHardDiskDrive -VMName "{vm_name}"; Set-VMFirmware -VMName "{vm_name}" -BootOrder $dvd,$hdd')

    # Disable Secure Boot (Ubuntu may need this)
    run_command(f'Set-VMFirmware -VMName "{vm_name}" -EnableSecureBoot Off')

    print(f"Storage created: {disk_size_gb}GB disk")
    print(f"ISO attached: {iso_path}")

def create_network_switch(vm_name, switch_name):
    """Create or use existing virtual switch"""
    print(f"\n[6/6] Configuring network...")

    # Check if switch exists
    success, stdout, _ = run_command(f'Get-VMSwitch -Name "{switch_name}"', check=False)

    if not success or switch_name not in stdout:
        print(f"Creating external virtual switch: {switch_name}...")
        print("This will use your default network adapter.")

        # Get default network adapter
        success, stdout, _ = run_command(
            "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty Name"
        )

        if success and stdout.strip():
            adapter_name = stdout.strip()
            cmd = f'New-VMSwitch -Name "{switch_name}" -NetAdapterName "{adapter_name}" -AllowManagementOS $true'
            run_command(cmd, check=False)
            print(f"Virtual switch created using adapter: {adapter_name}")
        else:
            print("WARNING: Could not create external switch. Creating internal switch instead.")
            run_command(f'New-VMSwitch -Name "{switch_name}" -SwitchType Internal')
    else:
        print(f"Using existing virtual switch: {switch_name}")

    # Connect VM to switch
    run_command(f'Add-VMNetworkAdapter -VMName "{vm_name}" -SwitchName "{switch_name}"')
    print(f"VM connected to network switch")

def start_vm(vm_name):
    """Start the VM"""
    print(f"\nStarting VM: {vm_name}...")
    run_command(f'Start-VM -Name "{vm_name}"')
    print("VM started")

    # Open VM console
    print("Opening VM console...")
    run_command(f'vmconnect localhost "{vm_name}"', check=False)

def print_summary(vm_name, memory_gb, cpu_count, disk_size_gb, switch_name, iso_path):
    """Print installation summary"""
    print("\n" + "="*50)
    print("VM Creation Complete!")
    print("="*50)

    print(f"\nVM Name: {vm_name}")
    print(f"\nResources:")
    print(f"  - RAM: {memory_gb}GB")
    print(f"  - CPUs: {cpu_count}")
    print(f"  - Disk: {disk_size_gb}GB")

    print(f"\nNetwork:")
    print(f"  - Virtual Switch: {switch_name}")

    print(f"\nISO: {iso_path}")

    print(f"\nAutostart:")
    print(f"  - VM will automatically start on host boot")
    print(f"  - Autostart delay: 10 seconds")

    print(f"\nInstallation:")
    print(f"  - Follow the Ubuntu installer in the VM console")
    print(f"  - After installation, remove the ISO:")
    print(f'    Get-VMDvdDrive -VMName "{vm_name}" | Remove-VMDvdDrive')

    print(f"\nUseful PowerShell Commands:")
    print(f'  Get-VM -Name "{vm_name}"                    # Show VM info')
    print(f'  Start-VM -Name "{vm_name}"                  # Start VM')
    print(f'  Stop-VM -Name "{vm_name}"                   # Shutdown VM')
    print(f'  Stop-VM -Name "{vm_name}" -Force            # Force shutdown')
    print(f'  vmconnect localhost "{vm_name}"             # Open console')
    print(f'  Get-VMNetworkAdapter -VMName "{vm_name}"    # Show network info')
    print(f'  Remove-VM -Name "{vm_name}" -Force          # Delete VM')

    print(f"\nAfter Ubuntu Installation:")
    print(f"  - Install SSH server in Ubuntu: sudo apt install openssh-server")
    print(f"  - Configure port forwarding or use bridged network for access")

    print("="*50)

def main():
    parser = argparse.ArgumentParser(description='Create Ubuntu 24.04 VM in Hyper-V')
    parser.add_argument('--vm-name', type=str, default='Ubuntu-24.04-Server',
                      help='VM name (default: Ubuntu-24.04-Server)')
    parser.add_argument('--iso-path', type=str, required=True,
                      help='Path to Ubuntu 24.04 ISO file')
    parser.add_argument('--memory', type=int, default=4,
                      help='RAM in GB (default: 4)')
    parser.add_argument('--cpus', type=int, default=2,
                      help='Number of CPUs (default: 2)')
    parser.add_argument('--disk-size', type=int, default=50,
                      help='Disk size in GB (default: 50)')
    parser.add_argument('--vm-path', type=str, default='C:\\ProgramData\\Microsoft\\Windows\\Hyper-V',
                      help='VM storage path (default: C:\\ProgramData\\Microsoft\\Windows\\Hyper-V)')
    parser.add_argument('--switch-name', type=str, default='External-Switch',
                      help='Virtual switch name (default: External-Switch)')
    parser.add_argument('--no-start', action='store_true',
                      help='Do not start VM after creation')

    args = parser.parse_args()

    print("="*50)
    print("Ubuntu 24.04 Hyper-V VM Creator")
    print("="*50)
    print()

    # Check prerequisites
    check_admin()
    check_hyperv()

    # Check ISO
    iso_path = download_ubuntu_iso(args.iso_path)

    # Create VM
    create_vm(args.vm_name, args.memory, args.cpus, args.disk_size, args.vm_path)

    # Create storage
    create_storage(args.vm_name, args.disk_size, iso_path, args.vm_path)

    # Configure network
    create_network_switch(args.vm_name, args.switch_name)

    # Start VM
    if not args.no_start:
        start_vm(args.vm_name)
    else:
        print("\nVM created but not started (--no-start flag)")

    # Print summary
    print_summary(args.vm_name, args.memory, args.cpus, args.disk_size, args.switch_name, iso_path)

if __name__ == "__main__":
    main()
