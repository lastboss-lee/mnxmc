"""
Two Panel Layout Widget

XenServer 스타일의 2패널 레이아웃을 구현합니다.
좌측 패널(메뉴, 32칸)과 우측 패널(콘텐츠, 나머지)로 구성됩니다.

Example:
    >>> with TwoPanelLayout():
    ...     yield MenuPanel()    # 자동으로 left-panel
    ...     yield ContentPanel() # 자동으로 right-panel
"""

from textual.containers import Container, Horizontal
from textual.widget import Widget
from textual.app import ComposeResult


class TwoPanelLayout(Horizontal):
    """
    XenServer 스타일 2패널 레이아웃 컨테이너.
    
    구조:
        - 좌측 패널: 32칸 고정, 메뉴 영역
        - 구분선: cyan 색상 세로선
        - 우측 패널: 나머지 공간, 콘텐츠 영역
    
    Attributes:
        DEFAULT_CSS: 기본 스타일 정의
    
    Example:
        >>> with TwoPanelLayout():
        ...     with LeftPanel():
        ...         yield MenuList(items=["Item 1", "Item 2"])
        ...     with RightPanel():
        ...         yield Static("Content here")
    """
    
    DEFAULT_CSS = """
    TwoPanelLayout {
        layout: horizontal;
        width: 100%;
        height: 100%;
        background: black;
    }
    
    TwoPanelLayout > .left-panel {
        width: 32;
        height: 100%;
        background: black;
        border-right: solid cyan;
        padding: 0;
    }
    
    TwoPanelLayout > .right-panel {
        width: 1fr;
        height: 100%;
        background: black;
        padding: 1 2;
    }
    """
    
    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """
        TwoPanelLayout을 초기화합니다.
        
        Args:
            *children: 자식 위젯들 (정확히 2개 필요)
            name: 위젯 이름
            id: 위젯 ID
            classes: CSS 클래스
            disabled: 비활성화 여부
        """
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
    
    def on_mount(self) -> None:
        """
        위젯이 마운트될 때 호출됩니다.
        
        자식 위젯 개수를 검증하고 클래스를 할당합니다.
        """
        children = list(self.children)
        
        if len(children) != 2:
            self.log.error(
                f"TwoPanelLayout expects exactly 2 children, got {len(children)}"
            )
            return
        
        # 첫 번째 자식에 left-panel 클래스 추가
        left_child = children[0]
        if "left-panel" not in left_child.classes:
            left_child.add_class("left-panel")
        
        # 두 번째 자식에 right-panel 클래스 추가
        right_child = children[1]
        if "right-panel" not in right_child.classes:
            right_child.add_class("right-panel")
        
        self.log.info(
            f"TwoPanelLayout mounted: left={left_child.__class__.__name__}, "
            f"right={right_child.__class__.__name__}"
        )


class LeftPanel(Container):
    """
    2패널 레이아웃의 좌측 패널.
    
    메뉴나 네비게이션 요소를 배치하는 영역입니다.
    기본 너비는 32칸으로 고정됩니다.
    """
    
    DEFAULT_CSS = """
    LeftPanel {
        width: 32;
        height: 100%;
        background: black;
        border-right: solid cyan;
        padding: 0;
    }
    """
    
    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """
        LeftPanel을 초기화합니다.
        
        Args:
            *children: 자식 위젯들
            name: 위젯 이름
            id: 위젯 ID
            classes: CSS 클래스
            disabled: 비활성화 여부
        """
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.add_class("left-panel")


class RightPanel(Container):
    """
    2패널 레이아웃의 우측 패널.
    
    메인 콘텐츠를 표시하는 영역입니다.
    남은 공간을 모두 사용합니다.
    """
    
    DEFAULT_CSS = """
    RightPanel {
        width: 1fr;
        height: 100%;
        background: black;
        padding: 1 2;
    }
    """
    
    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """
        RightPanel을 초기화합니다.
        
        Args:
            *children: 자식 위젯들
            name: 위젯 이름
            id: 위젯 ID
            classes: CSS 클래스
            disabled: 비활성화 여부
        """
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.add_class("right-panel")


class MenuTitle(Container):
    """
    메뉴 제목 컨테이너.
    
    좌측 패널 상단에 표시되는 제목 영역입니다.
    """
    
    DEFAULT_CSS = """
    MenuTitle {
        width: 100%;
        height: 1;
        background: black;
        color: cyan;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid cyan;
    }
    """