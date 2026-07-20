"""
Menu List Widget

XenServer 스타일의 메뉴 리스트 위젯을 구현합니다.
구분선, 섹션, 뒤로가기 등 특수 항목을 지원합니다.

Example:
    >>> menu = MenuList(
    ...     items=["System Overview", "Log Monitoring", "---", "← Back"],
    ...     title="Main Menu"
    ... )
"""

from typing import Callable, Optional

from textual.widgets import ListView, ListItem, Label, Static
from textual.message import Message
from textual.app import ComposeResult
from textual.binding import Binding


class MenuList(ListView):
    """
    XenServer 스타일 메뉴 리스트 위젯.
    
    다양한 메뉴 항목 유형을 지원합니다:
        - 일반 항목: 클릭 가능한 메뉴 아이템
        - 구분선: "───" 또는 "---"로 시작
        - 섹션 헤더: ":"로 끝남
        - 뒤로가기: "← Back" 또는 "Back"
    
    Attributes:
        menu_title: 메뉴 제목
        menu_items: 메뉴 항목 목록
    
    Messages:
        ItemSelected: 메뉴 항목이 선택되었을 때 발생
    
    Example:
        >>> menu = MenuList(
        ...     items=[
        ...         "System Overview",
        ...         "Log Monitoring",
        ...         "───────────────",
        ...         "Services:",
        ...         "  Kafka Status",
        ...         "  ES Status",
        ...         "───────────────",
        ...         "← Back"
        ...     ],
        ...     title="Dashboard"
        ... )
    """
    
    DEFAULT_CSS = """
    MenuList {
        background: black;
        border: none;
        padding: 0;
        width: 100%;
        height: 100%;
        scrollbar-size: 1 1;
    }
    
    MenuList:focus {
        border: none;
    }
    
    MenuList > ListItem {
        background: black;
        color: white;
        height: 1;
        padding: 0 1;
    }
    
    MenuList > ListItem:hover {
        background: white;
        color: black;
    }
    
    MenuList > ListItem.-separator {
        color: cyan;
        background: black;
    }
    
    MenuList > ListItem.-section {
        color: cyan;
        text-style: bold;
        background: black;
    }
    
    MenuList > ListItem.-back {
        color: yellow;
        background: black;
    }
    
    MenuList > ListItem.-disabled {
        color: #808080;
        background: black;
    }
    
    MenuList > ListItem.-selected {
        background: white;
        color: black;
    }
    """
    
    BINDINGS = [
        Binding("enter", "select_item", "Select", show=False),
        Binding("space", "select_item", "Select", show=False),
    ]
    
    class ItemSelected(Message):
        """
        메뉴 항목 선택 이벤트.
        
        Attributes:
            item_label: 선택된 항목의 텍스트
            item_index: 선택된 항목의 인덱스
        """
        
        def __init__(self, item_label: str, item_index: int = -1) -> None:
            """
            ItemSelected 메시지를 초기화합니다.
            
            Args:
                item_label: 선택된 항목의 텍스트
                item_index: 선택된 항목의 인덱스
            """
            super().__init__()
            self.item_label = item_label
            self.item_index = item_index
    
    def __init__(
        self,
        items: list[str],
        title: str = "Menu",
        show_title: bool = True,
        on_select: Optional[Callable[[str], None]] = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """
        MenuList를 초기화합니다.
        
        Args:
            items: 메뉴 항목 목록
            title: 메뉴 제목
            show_title: 제목 표시 여부
            on_select: 항목 선택 시 콜백 함수
            name: 위젯 이름
            id: 위젯 ID
            classes: CSS 클래스
        """
        super().__init__(name=name, id=id, classes=classes)
        self.menu_title = title
        self.menu_items = items
        self.show_title = show_title
        self._on_select_callback = on_select
        self._item_map: dict[int, str] = {}  # ListItem 인덱스 → 원본 텍스트
    
    def compose(self) -> ComposeResult:
        """
        메뉴 항목들을 구성합니다.
        
        Yields:
            ListItem: 구성된 메뉴 항목들
        """
        item_index = 0
        
        # 제목 (선택 불가)
        if self.show_title:
            title_item = ListItem(Label(f" {self.menu_title} "))
            title_item.add_class("-section")
            title_item.disabled = True
            yield title_item
            item_index += 1
            
            # 제목 구분선
            sep_item = ListItem(Label("─" * 30))
            sep_item.add_class("-separator")
            sep_item.disabled = True
            yield sep_item
            item_index += 1
        
        # 메뉴 항목들
        for menu_item in self.menu_items:
            list_item, is_selectable = self._create_menu_item(menu_item)
            yield list_item
            
            if is_selectable:
                self._item_map[item_index] = menu_item.strip()
            
            item_index += 1
    
    def _create_menu_item(self, text: str) -> tuple[ListItem, bool]:
        """
        메뉴 항목을 생성합니다.
        
        Args:
            text: 항목 텍스트
        
        Returns:
            tuple: (ListItem, 선택 가능 여부)
        """
        stripped = text.strip()
        
        # 구분선
        if stripped.startswith("─") or stripped.startswith("-" * 3):
            item = ListItem(Label(text))
            item.add_class("-separator")
            item.disabled = True
            return item, False
        
        # 섹션 헤더 (":"로 끝남)
        if stripped.endswith(":"):
            item = ListItem(Label(text))
            item.add_class("-section")
            item.disabled = True
            return item, False
        
        # 뒤로가기
        if "Back" in stripped or stripped.startswith("←"):
            item = ListItem(Label(f"  {stripped}"))
            item.add_class("-back")
            return item, True
        
        # 일반 항목
        item = ListItem(Label(f"  {stripped}"))
        return item, True
    
    def _get_label_text(self, label: Label) -> str:
        """
        Label 위젯에서 텍스트를 안전하게 추출합니다.
        
        Args:
            label: Label 위젯
        
        Returns:
            str: 추출된 텍스트
        """
        try:
            if hasattr(label, 'renderable'):
                return str(label.renderable)
        except Exception:
            pass
        
        try:
            if hasattr(label, 'render'):
                return str(label.render())
        except Exception:
            pass
        
        return "Unknown"
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """
        ListView 항목이 선택되었을 때 호출됩니다.
        
        Args:
            event: 선택 이벤트
        """
        try:
            item = event.item
            
            # 비활성화된 항목은 무시
            if item.disabled:
                return
            
            # Label에서 텍스트 추출
            label = item.query_one(Label)
            text = self._get_label_text(label).strip()
            
            # 앞 공백 및 마커 제거
            if text.startswith("▸ "):
                text = text[2:]
            if text.startswith("  "):
                text = text[2:]
            
            self.log.info(f"Menu item selected: '{text}'")
            
            # 메시지 발송
            self.post_message(self.ItemSelected(text))
            
            # 콜백 호출
            if self._on_select_callback:
                self._on_select_callback(text)
        
        except Exception as e:
            self.log.error(f"Selection handling error: {e}")
    
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """
        ListView 항목이 하이라이트되었을 때 호출됩니다.
        
        선택 표시자(▸)를 업데이트합니다.
        
        Args:
            event: 하이라이트 이벤트
        """
        try:
            for item in self.query(ListItem):
                if item.disabled:
                    continue
                
                try:
                    label = item.query_one(Label)
                    text = self._get_label_text(label).strip()
                    
                    # 기존 마커 제거
                    if text.startswith("▸ "):
                        text = text[2:]
                    if text.startswith("  "):
                        text = text[2:]
                    
                    # 현재 항목에만 마커 추가
                    if item == event.item:
                        label.update(f"▸ {text}")
                    else:
                        label.update(f"  {text}")
                
                except Exception:
                    pass
        
        except Exception as e:
            self.log.error(f"Highlight update error: {e}")
    
    def action_select_item(self) -> None:
        """
        현재 하이라이트된 항목을 선택합니다.
        
        Enter 또는 Space 키에 바인딩됩니다.
        """
        if self.highlighted_child is not None:
            self.post_message(
                ListView.Selected(self, self.highlighted_child)
            )
    
    def update_items(self, items: list[str]) -> None:
        """
        메뉴 항목을 업데이트합니다.
        
        Args:
            items: 새로운 메뉴 항목 목록
        """
        self.menu_items = items
        self._item_map.clear()
        self.clear()
        
        # 새 항목 추가
        for item_text in items:
            list_item, is_selectable = self._create_menu_item(item_text)
            self.append(list_item)
            
            if is_selectable:
                self._item_map[len(list(self.children)) - 1] = item_text.strip()


class SimpleMenu(Static):
    """
    간단한 정적 메뉴 위젯.
    
    ListView 없이 Static 기반으로 메뉴를 표시합니다.
    선택 기능이 필요 없는 정보 표시용으로 사용합니다.
    """
    
    DEFAULT_CSS = """
    SimpleMenu {
        width: 100%;
        height: auto;
        background: black;
        color: white;
        padding: 0 1;
    }
    """
    
    def __init__(
        self,
        items: list[str],
        title: str = "Menu",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """
        SimpleMenu를 초기화합니다.
        
        Args:
            items: 메뉴 항목 목록
            title: 메뉴 제목
            name: 위젯 이름
            id: 위젯 ID
            classes: CSS 클래스
        """
        content = self._format_menu(items, title)
        super().__init__(content, name=name, id=id, classes=classes)
    
    def _format_menu(self, items: list[str], title: str) -> str:
        """
        메뉴를 포맷팅합니다.
        
        Args:
            items: 메뉴 항목 목록
            title: 메뉴 제목
        
        Returns:
            str: 포맷팅된 메뉴 문자열
        """
        lines = [
            f"[bold cyan] {title} [/]",
            "[cyan]" + "─" * 30 + "[/]"
        ]
        
        for item in items:
            stripped = item.strip()
            
            if stripped.startswith("─") or stripped.startswith("-" * 3):
                lines.append(f"[cyan]{item}[/]")
            elif stripped.endswith(":"):
                lines.append(f"[cyan]{item}[/]")
            elif "Back" in stripped or stripped.startswith("←"):
                lines.append(f"[yellow]{item}[/]")
            else:
                lines.append(f"[white]  {stripped}[/]")
        
        return "\n".join(lines)