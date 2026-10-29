# Exact overview chord, handled within each session's native input boundary.
{ ... }:
{
  nixos.overview = { ... }: {
    # KWin's script API only registers keyboard shortcuts; use its native
    # pointer shortcut to invoke the same existing Overview QAction.
    nixpkgs.overlays = [
      (final: prev: {
        kdePackages = prev.kdePackages.overrideScope (
          _kfinal: kprev: {
            kwin = kprev.kwin.overrideAttrs (old: {
              postPatch = (old.postPatch or "") + ''
                substituteInPlace src/plugins/overview/overvieweffect.cpp \
                  --replace-fail 'overviewAction->setAutoRepeat(false);' \
                  'overviewAction->setAutoRepeat(false); effects->registerPointerShortcut(Qt::MetaModifier | Qt::ShiftModifier, Qt::MiddleButton, overviewAction);'
              '';
            });
          }
        );
      })
    ];
  };
}
