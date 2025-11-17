# -*- coding: utf-8 -*-
"""
CloudLab Profile for NVIDIA GH200 (nvidiagh) + H100 (Hopper)

Features
- Reserve nvidiagh nodes (default 1)
- Ubuntu 22.04 image
- Auto setup: Docker + NVIDIA Container Toolkit
- Enable nvidia-persistenced, print `nvidia-smi`
- Optional: basic conda bootstrap (commented, enable if needed)
- If nodes>1, auto-create a LAN between them

Usage
- In CloudLab "Create Experiment" -> "Import from Git repo"
- Repo path: <your GitHub repo>, File: profile.py
- Parameters: nodes, image_urn
"""

import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.emulab as emulab

pc = portal.Context()
req = pc.makeRequestRSpec()

# ---------- Parameters ----------
pnodes = pc.bindParameter(
    portal.Parameter(
        "nodes", portal.ParameterType.INTEGER, "Number of nodes",
        longDescription="How many nvidiagh nodes to allocate", defaultValue=1, min=1, max=16
    )
)

pimage = pc.bindParameter(
    portal.Parameter(
        "image_urn", portal.ParameterType.STRING, "Disk image URN",
        longDescription="Leave default unless you have a custom image",
        defaultValue="urn:publicid:IDN+utah.cloudlab.us+image+Canonical:ubuntu-22.04"
    )
)

pc.verifyParameters()

# ---------- Common setup script ----------
SETUP_BASH = r"""#!/usr/bin/env bash
set -euxo pipefail

echo "[INFO] Node: $(hostname)  Arch: $(uname -m)  Kernel: $(uname -r)"

# 0) Basic packages
sudo apt-get update -y
sudo apt-get install -y git curl wget ca-certificates gnupg lsb-release \
    pciutils net-tools htop jq build-essential

# 1) NVIDIA driver usually comes with GPU images on CloudLab.
#    We do NOT re-install the driver; just verify.
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[INFO] nvidia-smi found:"
  nvidia-smi || true
else
  echo "[WARN] nvidia-smi not found. Please use a GPU-enabled image or install driver manually."
fi

# 2) Docker
if ! command -v docker >/dev/null 2>&1; then
  echo "[INFO] Installing Docker..."
  sudo apt-get remove -y docker docker-engine docker.io containerd runc || true
  sudo apt-get install -y apt-transport-https software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo $UBUNTU_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io
  sudo usermod -aG docker $USER || true
fi

# 3) NVIDIA Container Toolkit
echo "[INFO] Installing NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release; echo $ID$VERSION_ID) && \
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg && \
  curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update -y
sudo apt-get install -y nvidia-container-toolkit

sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker || true

# 4) Enable persistence & quick self-check
if command -v nvidia-smi >/dev/null 2>&1; then
  sudo nvidia-smi -pm 1 || true
  echo "[INFO] Docker + GPU test"
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi || true
fi

# 5) Optional: bootstrap conda (comment out if not needed)
# ARCH=$(uname -m)
# if [ "$ARCH" = "aarch64" ]; then
#   CONDA_SH=Miniforge3-Linux-aarch64.sh
#   URL=https://github.com/conda-forge/miniforge/releases/latest/download/$CONDA_SH
# else
#   CONDA_SH=Miniforge3-Linux-x86_64.sh
#   URL=https://github.com/conda-forge/miniforge/releases/latest/download/$CONDA_SH
# fi
# wget -q $URL -O /tmp/$CONDA_SH
# bash /tmp/$CONDA_SH -b -p $HOME/miniforge
# echo 'export PATH="$HOME/miniforge/bin:$PATH"' >> $HOME/.bashrc

echo "[DONE] Setup complete."
"""

def add_node(idx: int):
    n = req.RawPC(f"node{idx+1}")
    n.hardware_type = "nvidiagh"              # GH200 superchip node class
    n.disk_image = pimage.value               # Ubuntu 22.04 by default
    n.InstallScript(common=True, script=SETUP_BASH)  # Emulab extension: upload & run script

    # Optional: expose NVMe mount points via metadata (just a hint for users)
    n.addService(pg.Execute(shell="bash", command="echo '[INFO] Local NVMe:'; lsblk -o NAME,SIZE,MODEL || true"))

    # More permissive sysctls for DL workloads (optional)
    sysctl = n.addService(pg.Execute(shell="bash", command="""
sudo bash -c 'cat >/etc/sysctl.d/99-dl-tuning.conf <<EOF
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=1024
vm.max_map_count=1048576
EOF'
sudo sysctl --system || true
"""))
    return n

nodes = []
for i in range(pnodes.value):
    nodes.append(add_node(i))

# If multiple nodes, create a simple LAN
if pnodes.value > 1:
    lan = req.Link("lan")
    lan.best_effort = True
    lan.vlan_tagging = True
    for n in nodes:
        iface = n.addInterface(f"if{i}")
        lan.addInterface(iface)

pc.printRequestRSpec(req)
