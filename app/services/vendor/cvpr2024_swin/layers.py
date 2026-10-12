"""Inference helpers replacing timm; no training or stochastic depth export."""
from torch import nn
from torch.nn.init import trunc_normal_
from torch.nn.modules.utils import _pair as to_2tuple


class DropPath(nn.Module):
    def __init__(self, drop_prob=0.):
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, value):
        if self.training and self.drop_prob:
            raise RuntimeError('This vendored adapter supports evaluation/export only.')
        return value
