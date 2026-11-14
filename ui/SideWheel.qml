// A sideways row (cast, Gallery, Continue Watching) inside a page that scrolls up and down. Put two inside the row's
// ListView and set the ListView's interactive: false:
//   ListView { id: row; orientation: ListView.Horizontal; interactive: false
//              SideWheel { view: row }  SideWheel { view: row; shift: true } }
// A sideways wheel or touchpad swipe (or, with shift: true, Shift + wheel) scrolls the row. A plain up/down wheel is
// never taken here, so it scrolls the page as if the row were not there.
import QtQuick

WheelHandler {
    id: root
    required property Flickable view
    property bool shift: false
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    orientation: shift ? Qt.Vertical : Qt.Horizontal          // only these events are offered to this handler
    acceptedModifiers: shift ? Qt.ShiftModifier : Qt.KeyboardModifierMask
    readonly property real right: view.originX + Math.max(0, view.contentWidth - view.width)
    onWheel: (ev) => {
        var d = shift ? (ev.pixelDelta.y !== 0 ? ev.pixelDelta.y : ev.angleDelta.y)
                      : (ev.pixelDelta.x !== 0 ? ev.pixelDelta.x : ev.angleDelta.x)
        view.contentX = Math.max(view.originX, Math.min(right, view.contentX - d))
    }
}
