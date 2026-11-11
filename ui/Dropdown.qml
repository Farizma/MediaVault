// Themed dropdown. options: [{value, label}]; `value` is the chosen value; chosen(value) when the person picks.
import QtQuick
import QtQuick.Controls

ComboBox {
    id: drop
    property var options: []
    property string value: ""
    property string prefix: ""            // e.g. "Sort: "
    signal chosen(string value)
    implicitHeight: 32
    implicitWidth: Math.max(120, label.implicitWidth + 44)
    model: options
    textRole: "label"
    currentIndex: { for (var i = 0; i < options.length; i++) if (options[i].value === value) return i; return 0 }
    onActivated: (i) => { drop.value = options[i].value; drop.chosen(options[i].value) }
    font.pixelSize: 12
    background: Rectangle {
        radius: 10
        color: drop.popup.visible ? Qt.rgba(1, 1, 1, 0.16) : (drop.hovered ? Qt.rgba(1, 1, 1, 0.12) : Theme.fill)
        border.color: drop.popup.visible ? Theme.blue : Theme.line
        Behavior on color { ColorAnimation { duration: 120 * Theme.motion } }
    }
    contentItem: Text {
        id: label
        leftPadding: 12; rightPadding: 28
        text: drop.prefix + (drop.currentIndex >= 0 && drop.options.length ? drop.options[drop.currentIndex].label : "")
        color: Theme.soft; font.pixelSize: 12; font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Text {
        x: drop.width - width - 10; anchors.verticalCenter: parent.verticalCenter
        text: "⌄"; color: Theme.faint; font.pixelSize: 13
        rotation: drop.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
    }
    delegate: ItemDelegate {
        width: Math.max(drop.width, 180) - 8
        height: 32
        highlighted: drop.highlightedIndex === index
        background: Rectangle { radius: 8; color: parent.highlighted ? Qt.rgba(1, 1, 1, 0.12) : "transparent" }
        contentItem: Item {
            Text { anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 20 }
                text: modelData.label; elide: Text.ElideRight; font.pixelSize: 12
                color: modelData.value === drop.value ? Theme.text : Theme.soft; font.weight: modelData.value === drop.value ? Font.Bold : Font.Normal }
            Text { visible: modelData.value === drop.value; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                text: "✓"; color: Theme.green; font.pixelSize: 12; font.weight: Font.Bold }
        }
    }
    popup: Popup {
        y: drop.height + 6
        width: Math.max(drop.width, 180)
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4
        transformOrigin: Item.Top
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
            NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: 200 * Theme.motion; easing.type: Easing.OutCubic } } }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 120 * Theme.motion } }
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: drop.popup.visible ? drop.delegateModel : null
            currentIndex: drop.highlightedIndex; ScrollIndicator.vertical: ScrollIndicator {} }
        background: Rectangle { radius: 12; color: Theme.panel; border.color: Theme.edge }
    }
}
