import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// DualSense cheat sheet. iris-controller summons and hides it each time the
// mic button is pressed. Every word comes from the payload (the script's
// live keymap); this file only knows where each part sits on the pad:
//   { "parts":      { "cross": { "name": "✕", "actions": ["Click"] }, ... },
//     "categories": [ { "title": "Typing",
//                       "rows": [ { "keys": ["R2", "□"], "action": "Space" }, ... ] }, ... ] }
Item {
  id: root

  property bool opened: false
  property var parts: ({})
  property var categories: []

  // The sheet is laid out this wide, as tall as its content, and the card
  // is scaled down until it fits the monitor.
  readonly property int sheetW: 1900
  readonly property int pad: 40

  // Controller drawing: anchors are in its 1000 x 703 box, placed mid-sheet.
  readonly property real padScale: 0.7
  readonly property real padX: (sheetW - 1000 * padScale) / 2
  readonly property real padY: 96

  // Label columns either side of the drawing, and the band they may use.
  readonly property int colW: 540
  readonly property int leftColRight: 560
  readonly property int rightColLeft: sheetW - 560
  readonly property int bandTop: 80
  readonly property int bandBottom: 560
  readonly property int lineH: 28
  readonly property int labelGap: 12
  readonly property int listsTop: 610

  readonly property color ink: Color.popups.text
  readonly property color faint: Util.alpha(Color.popups.text, 0.55)
  readonly property color hud: Color.accent

  // PlayStation symbol colors.
  readonly property var symbolColor: ({
    "triangle": "#3fc8a8", "circle": "#e8616b", "cross": "#7b9fe8", "square": "#d58ad8"
  })

  // Hardware layout: where the leader line touches each part (drawing units),
  // and which side of the sheet its label goes.
  readonly property var anchorsLeft: ({
    "l2": [180, 10], "l1": [128, 42], "create": [267, 80], "touchpad": [420, 130],
    "dpad": [150, 190], "lstick": [330, 330], "mic": [485, 380]
  })
  readonly property var anchorsRight: ({
    "r2": [820, 10], "r1": [872, 42], "options": [733, 80], "triangle": [842, 115],
    "circle": [917, 190], "square": [738, 222], "cross": [842, 262],
    "rstick": [670, 330], "ps": [505, 318]
  })

  function sheetPoint(a) { return [padX + a[0] * padScale, padY + a[1] * padScale] }

  // Stack one column's labels in anchor order, each as close to its anchor's
  // height as the ones above it allow, then pull the stack back inside the band.
  function layoutSide(anchorMap) {
    var items = []
    for (var id in anchorMap) {
      var part = root.parts[id]
      if (!part || !part.actions || part.actions.length === 0) continue
      var p = sheetPoint(anchorMap[id])
      items.push({ id: id, ax: p[0], ay: p[1], h: part.actions.length * lineH })
    }
    items.sort(function(a, b) { return a.ay - b.ay || a.ax - b.ax })
    var y = bandTop
    for (var i = 0; i < items.length; i++) {
      items[i].y = Math.max(items[i].ay - lineH / 2, y)
      y = items[i].y + items[i].h + labelGap
    }
    var over = y - labelGap - bandBottom
    for (var j = items.length - 1; j >= 0 && over > 0; j--) {
      var limit = j === 0 ? bandTop : items[j - 1].y + items[j - 1].h + labelGap
      var shift = Math.min(over, items[j].y - limit)
      for (var k = j; k < items.length; k++) items[k].y -= shift
      over -= shift
    }
    return items
  }

  readonly property var leftLabels: layoutSide(anchorsLeft)
  readonly property var rightLabels: layoutSide(anchorsRight)

  // Category cards under the drawing, this many per row.
  readonly property int catColumns: 4
  readonly property int catGap: 40
  readonly property real catW: (sheetW - (catColumns - 1) * catGap) / catColumns

  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  function open(payloadJson) {
    try {
      var p = JSON.parse(payloadJson || "{}")
      root.parts = p.parts || {}
      root.categories = p.categories || []
    } catch (e) {}
    root.opened = true
  }

  function close() { root.opened = false }

  // --- pieces ---------------------------------------------------------------

  // A button name as it reads on the pad: colored symbol for face buttons.
  component PartName: Text {
    property string partId: ""
    textFormat: Text.PlainText
    font.family: Style.font.family
    font.bold: true
    font.pixelSize: root.symbolColor[partId] ? 24 : 17
    font.letterSpacing: root.symbolColor[partId] ? 0 : 1.5
    font.capitalization: Font.AllUppercase
    color: root.symbolColor[partId] || root.hud
  }

  // One callout: name and actions, aligned toward the drawing.
  component Callout: Item {
    property var entry
    property bool leftSide: false
    readonly property var part: root.parts[entry.id] || { name: "", actions: [] }
    x: leftSide ? root.leftColRight - root.colW : root.rightColLeft
    y: entry.y
    width: root.colW
    height: entry.h

    Row {
      anchors.fill: parent
      layoutDirection: leftSide ? Qt.RightToLeft : Qt.LeftToRight
      spacing: 14

      PartName {
        id: nameText
        partId: entry.id
        text: part.name
        height: root.lineH
        verticalAlignment: Text.AlignVCenter
      }

      Column {
        width: parent.width - nameText.width - parent.spacing
        Repeater {
          model: part.actions
          Text {
            required property string modelData
            width: parent.width
            textFormat: Text.PlainText
            text: modelData
            height: root.lineH
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: leftSide ? Text.AlignRight : Text.AlignLeft
            font.family: Style.font.family
            font.pixelSize: 18
            fontSizeMode: Text.HorizontalFit   // an overlong line shrinks, never spills
            minimumPixelSize: 12
            color: Util.alpha(root.ink, 0.85)
          }
        }
      }
    }
  }

  // A key chip for the combo lists.
  component Key: Rectangle {
    property string label: ""
    readonly property string symbolId: {
      for (var id in root.symbolColor) {
        var p = root.parts[id]
        if (p && p.name === label) return id
      }
      return ""
    }
    implicitWidth: keyText.implicitWidth + 20
    implicitHeight: 32
    radius: 2
    color: Util.alpha(root.hud, 0.08)
    border.width: 1
    border.color: Util.alpha(root.hud, 0.4)
    Text {
      id: keyText
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: parent.label
      font.family: Style.font.family
      font.bold: true
      font.pixelSize: parent.symbolId ? 20 : 16
      color: root.symbolColor[parent.symbolId] || root.ink
    }
  }

  // "// TITLE ────────" section header.
  component SectionTitle: Row {
    property string title: ""
    width: parent ? parent.width : 0
    spacing: 14
    Text {
      id: titleText
      textFormat: Text.PlainText
      text: "// " + parent.title
      font.family: Style.font.family
      font.bold: true
      font.pixelSize: 17
      font.letterSpacing: 3
      font.capitalization: Font.AllUppercase
      color: root.hud
    }
    Rectangle {
      anchors.verticalCenter: titleText.verticalCenter
      width: parent.width - titleText.width - parent.spacing
      height: 1
      color: Util.alpha(root.hud, 0.3)
    }
  }

  // One category's rows: key chips, then what they do. The text shrinks
  // rather than spill past the card.
  component CategoryRows: Column {
    property var rows: []
    spacing: 10

    Repeater {
      model: parent.rows
      Row {
        id: catRow
        required property var modelData
        spacing: 10

        Row {
          id: chips
          spacing: 6
          anchors.verticalCenter: parent.verticalCenter
          Repeater {
            model: catRow.modelData.keys
            Key { required property string modelData; label: modelData }
          }
        }

        Text {
          text: "▸"
          anchors.verticalCenter: parent.verticalCenter
          font.family: Style.font.family
          font.pixelSize: 18
          color: root.hud
        }

        Text {
          width: root.catW - chips.width - 40
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: catRow.modelData.action
          font.family: Style.font.family
          font.pixelSize: 18
          fontSizeMode: Text.HorizontalFit
          minimumPixelSize: 12
          color: root.ink
        }
      }
    }
  }

  // --- window -----------------------------------------------------------------

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-help"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    // Look-only: an empty input region so it never eats clicks.
    mask: Region {}

    readonly property real fit: Math.min(1,
      (panel.width * 0.94) / card.width,
      (panel.height * 0.92) / card.height)

    // Dim the desktop so the card reads as a HUD over it.
    Rectangle {
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.55)
    }

    Item {
      id: card
      anchors.centerIn: parent
      width: root.sheetW + 2 * root.pad
      height: sheet.height + 2 * root.pad
      scale: panel.fit

      readonly property int cut: 28   // chamfered corners

      // Frame: chamfered top-left and bottom-right, brackets on the others.
      Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: Util.alpha(root.hud, 0.55); strokeWidth: 1.5
          fillColor: Util.alpha(Color.background, 0.94)
          PathSvg {
            path: "M " + card.cut + " 0 L " + card.width + " 0 L " + card.width + " " + (card.height - card.cut)
                + " L " + (card.width - card.cut) + " " + card.height + " L 0 " + card.height
                + " L 0 " + card.cut + " Z"
          }
        }
        ShapePath {
          strokeColor: root.hud; strokeWidth: 4; fillColor: "transparent"
          capStyle: ShapePath.FlatCap
          PathSvg {
            path: "M " + (card.width - 70) + " 2 L " + (card.width - 2) + " 2 L " + (card.width - 2) + " 70 "
                + "M 2 " + (card.height - 70) + " L 2 " + (card.height - 2) + " L 70 " + (card.height - 2)
                + " M " + (card.cut + 4) + " 2 L " + (card.cut + 90) + " 2"
          }
        }
      }

      // Faint grid behind everything.
      Canvas {
        anchors.fill: parent
        anchors.margins: 2
        property color line: Util.alpha(root.hud, 0.05)
        onLineChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
          var ctx = getContext("2d")
          ctx.reset()
          ctx.strokeStyle = line
          ctx.lineWidth = 1
          for (var x = 40; x < width; x += 40) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke()
          }
          for (var y = 40; y < height; y += 40) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
          }
        }
      }

      Item {
        id: sheet
        x: root.pad
        y: root.pad
        width: root.sheetW
        height: lists.y + lists.height

        // Header
        Text {
          id: tag
          textFormat: Text.PlainText
          text: "◢ IRIS·CTRL"
          font.family: Style.font.family
          font.bold: true
          font.pixelSize: 15
          font.letterSpacing: 3
          color: root.hud
        }
        Text {
          id: title
          anchors.left: tag.right
          anchors.leftMargin: 18
          anchors.baseline: tag.baseline
          textFormat: Text.PlainText
          text: "DUALSENSE // INPUT MAP"
          font.family: Style.font.family
          font.bold: true
          font.pixelSize: 30
          font.letterSpacing: 4
          color: root.ink
        }
        Row {
          anchors.right: parent.right
          anchors.verticalCenter: title.verticalCenter
          spacing: 10
          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 9; height: 9; radius: 4.5
            color: root.hud
            SequentialAnimation on opacity {
              running: root.opened
              loops: Animation.Infinite
              NumberAnimation { to: 0.2; duration: 700 }
              NumberAnimation { to: 1; duration: 700 }
            }
          }
          Text {
            textFormat: Text.PlainText
            text: "LINK ACTIVE · ANY BUTTON TO CLOSE"
            font.family: Style.font.family
            font.pixelSize: 15
            font.letterSpacing: 2
            color: root.faint
          }
        }
        Rectangle {
          y: title.y + title.height + 12
          width: parent.width
          height: 1
          color: Util.alpha(root.hud, 0.3)
        }

        // Soft glow behind the pad.
        Rectangle {
          x: root.padX + 60
          y: root.padY + 20
          width: 1000 * root.padScale - 120
          height: 703 * root.padScale - 40
          radius: height / 2
          gradient: Gradient {
            GradientStop { position: 0; color: Util.alpha(root.hud, 0.0) }
            GradientStop { position: 0.5; color: Util.alpha(root.hud, 0.10) }
            GradientStop { position: 1; color: Util.alpha(root.hud, 0.0) }
          }
        }

        // The controller: our own flat drawing (dualsense.svg, no logos),
        // shown in a 1000 x 703 box the anchors are measured in.
        Image {
          x: root.padX
          y: root.padY
          width: 1000 * root.padScale
          height: 703 * root.padScale
          source: "dualsense.svg"
          fillMode: Image.PreserveAspectFit
          smooth: true
          mipmap: true
        }

        // Leader lines: from the part, diagonal to the column, short run into the label.
        Canvas {
          id: leaders
          anchors.fill: parent
          antialiasing: true
          z: 1
          readonly property var labels: root.leftLabels.concat(root.rightLabels)
          property color line: Util.alpha(root.hud, 0.55)
          onLabelsChanged: requestPaint()
          onLineChanged: requestPaint()
          onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = line
            ctx.lineWidth = 1.5
            for (var i = 0; i < labels.length; i++) {
              var l = labels[i]
              var left = l.ax < root.sheetW / 2
              var ly = l.y + root.lineH / 2
              var edge = left ? root.leftColRight + 12 : root.rightColLeft - 12
              ctx.beginPath()
              ctx.moveTo(l.ax, l.ay)
              ctx.lineTo(edge + (left ? 30 : -30), ly)
              ctx.lineTo(edge, ly)
              ctx.stroke()
              ctx.fillStyle = line
              ctx.fillRect(edge - (left ? 0 : 4), ly - 2, 4, 4)
            }
          }
        }

        // Targets on each part: a ring around a dot.
        Repeater {
          model: root.leftLabels.concat(root.rightLabels)
          Item {
            required property var modelData
            x: modelData.ax - 8
            y: modelData.ay - 8
            width: 16
            height: 16
            z: 2
            Rectangle {
              anchors.fill: parent
              radius: 8
              color: "transparent"
              border.width: 1.5
              border.color: root.hud
            }
            Rectangle {
              anchors.centerIn: parent
              width: 6; height: 6; radius: 3
              color: root.hud
            }
          }
        }

        Repeater {
          model: root.leftLabels
          Callout { required property var modelData; entry: modelData; leftSide: true }
        }
        Repeater {
          model: root.rightLabels
          Callout { required property var modelData; entry: modelData; leftSide: false }
        }

        // The categories, under the drawing. The sheet ends where they do.
        Grid {
          id: lists
          y: root.listsTop
          columns: root.catColumns
          columnSpacing: root.catGap
          rowSpacing: 34

          Repeater {
            model: root.categories
            Column {
              required property var modelData
              width: root.catW
              spacing: 16
              SectionTitle { title: modelData.title }
              CategoryRows { rows: modelData.rows }
            }
          }
        }
      }
    }
  }
}
