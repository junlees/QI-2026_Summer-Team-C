from torch.optim.lr_scheduler import CosineAnnealingLR, LinearLR, SequentialLR


class WarmupCosineAnnealingLR(SequentialLR):
    """Linear warmup followed by cosine decay, stepped once per epoch."""

    def __init__(self, optimizer, warmup_epochs, total_epochs,
                 start_factor=0.1, eta_min=0.0, last_epoch=-1):
        if not 0 < warmup_epochs < total_epochs:
            raise ValueError('warmup_epochs must be between 1 and total_epochs - 1')

        warmup = LinearLR(
            optimizer,
            start_factor=start_factor,
            end_factor=1.0,
            total_iters=warmup_epochs,
        )
        cosine = CosineAnnealingLR(
            optimizer,
            T_max=total_epochs - warmup_epochs,
            eta_min=eta_min,
        )
        super().__init__(
            optimizer,
            schedulers=[warmup, cosine],
            milestones=[warmup_epochs],
            last_epoch=last_epoch,
        )
