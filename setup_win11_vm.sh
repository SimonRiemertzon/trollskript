#!/bin/bash
set -e

ISO="/home/siniom/repos/trollskript/Win11_25H2_English_x64.iso"
VM_NAME="Windows11"
VDI="$HOME/VMs/Windows11.vdi"

echo "=== Step 1: Adding VirtualBox repository ==="
wget -q -O- https://www.virtualbox.org/download/oracle_vbox_2016.asc \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/oracle-virtualbox.gpg

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/oracle-virtualbox.gpg] \
https://download.virtualbox.org/virtualbox/debian jammy contrib" \
  | sudo tee /etc/apt/sources.list.d/virtualbox.list

echo "=== Step 2: Installing VirtualBox 7 ==="
sudo apt update

# Try 7.1 first, fall back to 7.0
if apt-cache show virtualbox-7.1 &>/dev/null; then
  sudo apt install -y virtualbox-7.1
elif apt-cache show virtualbox-7.0 &>/dev/null; then
  sudo apt install -y virtualbox-7.0
else
  echo "ERROR: Could not find VirtualBox 7.x in the repository."
  exit 1
fi

echo "=== Step 3: Creating VM ==="
mkdir -p ~/VMs

# Clean up any pre-existing VM with the same name
if VBoxManage showvminfo "$VM_NAME" &>/dev/null; then
  echo "Removing existing VM: $VM_NAME"
  VBoxManage unregistervm "$VM_NAME" --delete
fi

VBoxManage createvm --name "$VM_NAME" --ostype Windows11_64 --register

VBoxManage modifyvm "$VM_NAME" \
  --memory 4096 \
  --cpus 2 \
  --tpm-type 2.0 \
  --firmware efi \
  --graphicscontroller vmsvga \
  --vram 128

# Remove leftover VDI if it exists (e.g. from a previous failed run)
if [ -f "$VDI" ]; then
  echo "Removing leftover VDI: $VDI"
  VBoxManage closemedium disk "$VDI" --delete 2>/dev/null || rm -f "$VDI"
fi

VBoxManage createhd --filename "$VDI" --size 50000

VBoxManage storagectl "$VM_NAME" --name "SATA" --add sata

VBoxManage storageattach "$VM_NAME" \
  --storagectl "SATA" --port 0 --device 0 --type hdd --medium "$VDI"

VBoxManage storageattach "$VM_NAME" \
  --storagectl "SATA" --port 1 --device 0 --type dvddrive --medium "$ISO"

echo "=== Done! Starting VM ==="
VBoxManage startvm "$VM_NAME"

