// One card on a folder-cards tab (Artists): your picture for the folder, else a mosaic of its newest covers, else
// its initials; then its name and how many videos it holds. All videos and Unsorted get a symbol instead.
//   FolderCard { width: 180; info: {rel, name, count, fav, picture, covers, kind}; onOpen: ...; onMenu: (item, x, y) => ... }
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property var info: ({})
    signal open()
    signal menu(var item, real x, real y)
    height: tile.height + 52
    readonly property var covers: info.covers || []
    readonly property bool special: info.kind !== "folder"

    Rectangle {
        id: tile
        width: parent.width; height: width
        radius: 16
        color: Theme.slate
        border.color: hover.hovered ? "#66FFFFFF" : Theme.line
        border.width: hover.hovered ? 1.5 : 1
        scale: tap.pressed ? 0.97 : hover.hovered ? 1.03 : 1
        Behavior on scale { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
        Behavior on border.color { ColorAnimation { duration: 160 * Theme.motion } }

        Item {
            id: art
            anchors.fill: parent
            visible: false
            // your picture
            Image { anchors.fill: parent; visible: root.info.picture !== ""; source: root.info.picture || ""
                fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 360; sourceSize.height: 360 }
            // a mosaic of covers: one fills the card, two split it, three or four make a 2 x 2
            Grid {
                anchors.fill: parent
                visible: root.info.picture === "" && root.covers.length > 0
                columns: root.covers.length > 1 ? 2 : 1
                spacing: 2
                Repeater {
                    model: root.covers.length === 3 ? root.covers.concat([root.covers[0]]) : root.covers
                    Image {
                        width: root.covers.length > 1 ? (art.width - 2) / 2 : art.width
                        height: root.covers.length > 2 ? (art.height - 2) / 2 : art.height
                        source: modelData; fillMode: Image.PreserveAspectCrop; asynchronous: true
                        sourceSize.width: 200; sourceSize.height: 200
                    }
                }
            }
        }
        Item { id: mask; anchors.fill: parent; visible: false; layer.enabled: true
            Rectangle { anchors.fill: parent; radius: tile.radius } }
        MultiEffect { source: art; anchors.fill: art; maskEnabled: true; maskSource: mask
            visible: root.info.picture !== "" || root.covers.length > 0 }
        // a soft shade at the bottom for All videos / Unsorted over their mosaic
        Rectangle { anchors.fill: parent; radius: tile.radius; visible: root.special
            gradient: Gradient { GradientStop { position: 0; color: "#33000000" } GradientStop { position: 1; color: "#B3000000" } } }
        Text {
            anchors.centerIn: parent
            visible: root.special || (root.info.picture === "" && root.covers.length === 0)
            text: root.info.kind === "all" ? "▦" : root.info.kind === "loose" ? "☰"
                  : (root.info.name || "?").split(/\s+/).filter(function(w) { return w.length }).slice(0, 2).map(function(w) { return w[0].toUpperCase() }).join("")
            color: "#FFFFFF"; font.pixelSize: root.special ? 40 : 44; font.weight: Font.Bold; opacity: 0.9
        }
        // pinned to the front
        Rectangle {
            visible: root.info.fav === true
            x: 10; y: 10; width: 26; height: 26; radius: 13
            color: "#B3000000"; border.color: "#40FFFFFF"
            Text { anchors.centerIn: parent; text: "★"; color: Theme.amber; font.pixelSize: 13 }
        }
        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tap; acceptedButtons: Qt.LeftButton; onTapped: root.open() }
        TapHandler { acceptedButtons: Qt.RightButton; onTapped: (pt) => root.menu(tile, pt.position.x, pt.position.y) }
    }
    Text {
        anchors { top: tile.bottom; topMargin: 10; left: parent.left; right: parent.right }
        text: root.info.name || ""
        color: "#FFFFFF"; font.pixelSize: 14; font.weight: Font.Bold
        elide: Text.ElideRight
    }
    Text {
        anchors { top: tile.bottom; topMargin: 30; left: parent.left; right: parent.right }
        text: (root.info.count || 0) + ((root.info.count || 0) === 1 ? " video" : " videos")
        color: "#66FFFFFF"; font.family: Theme.mono; font.pixelSize: 11
    }
}
