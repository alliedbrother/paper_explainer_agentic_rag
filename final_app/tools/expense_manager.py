"""Expense manager tool for tracking user expenses."""

from datetime import date, datetime
from typing import Literal, Optional
from decimal import Decimal

from langchain_core.tools import tool
import psycopg2
from psycopg2.extras import RealDictCursor

from ..config import get_settings

settings = get_settings()


def get_db_connection():
    """Get synchronous PostgreSQL connection for tools."""
    return psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname=settings.postgres_db,
    )


@tool
def expense_manager(
    action: Literal["add", "list", "summary", "delete"],
    amount: Optional[float] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    expense_date: Optional[str] = None,
    expense_id: Optional[str] = None,
) -> str:
    """Manage user expenses - add, list, summarize, or delete.

    The user_id is automatically determined from the session context.

    Args:
        action: Action to perform
            - "add": Add a new expense (requires amount, category)
            - "list": List expenses (optional category filter)
            - "summary": Get spending summary by category
            - "delete": Delete an expense (requires expense_id)
        amount: Expense amount (required for "add")
        category: Expense category (e.g., "food", "transport", "entertainment")
        description: Optional description of the expense
        expense_date: Date of expense in YYYY-MM-DD format (defaults to today)
        expense_id: Expense ID (required for "delete")

    Returns:
        Result message with expense data
    """
    from ..services.progress_tracker import get_current_user_id

    # Get user_id from session context
    user_id = get_current_user_id()
    if not user_id:
        return "Error: No user session found. Please log in to manage expenses."

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if action == "add":
            if amount is None or category is None:
                return "Error: 'add' action requires amount and category"

            exp_date = date.today()
            if expense_date:
                try:
                    exp_date = datetime.strptime(expense_date, "%Y-%m-%d").date()
                except ValueError:
                    return "Error: Invalid date format. Use YYYY-MM-DD"

            cursor.execute(
                """
                INSERT INTO expenses (user_id, amount, category, description, expense_date)
                VALUES (%s::uuid, %s, %s, %s, %s)
                RETURNING id, amount, category, expense_date
                """,
                (user_id, Decimal(str(amount)), category, description, exp_date),
            )
            conn.commit()
            result = cursor.fetchone()

            return (
                f"Added expense: ${float(result['amount']):.2f} in '{result['category']}' "
                f"on {result['expense_date']}"
                + (f" - {description}" if description else "")
            )

        elif action == "list":
            query = """
                SELECT id, amount, category, description, expense_date
                FROM expenses
                WHERE user_id = %s::uuid
            """
            params = [user_id]

            if category:
                query += " AND category = %s"
                params.append(category)

            query += " ORDER BY expense_date DESC LIMIT 20"

            cursor.execute(query, params)
            expenses = cursor.fetchall()

            if not expenses:
                return f"No expenses found" + (
                    f" in category '{category}'" if category else ""
                )

            lines = [f"**Expenses for user**" + (f" in '{category}'" if category else "") + ":"]
            total = 0
            for exp in expenses:
                amount_val = float(exp["amount"])
                total += amount_val
                desc = f" - {exp['description']}" if exp["description"] else ""
                lines.append(
                    f"- {exp['expense_date']}: ${amount_val:.2f} ({exp['category']}){desc}"
                )

            lines.append(f"\n**Total:** ${total:.2f}")
            return "\n".join(lines)

        elif action == "summary":
            cursor.execute(
                """
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM expenses
                WHERE user_id = %s::uuid
                GROUP BY category
                ORDER BY total DESC
                """,
                (user_id,),
            )
            summary = cursor.fetchall()

            if not summary:
                return "No expenses recorded yet."

            lines = ["**Expense Summary by Category:**"]
            grand_total = 0
            for item in summary:
                total = float(item["total"])
                grand_total += total
                lines.append(f"- {item['category'].title()}: ${total:.2f} ({item['count']} transactions)")

            lines.append(f"\n**Grand Total:** ${grand_total:.2f}")
            return "\n".join(lines)

        elif action == "delete":
            if expense_id is None:
                return "Error: 'delete' action requires expense_id"

            cursor.execute(
                """
                DELETE FROM expenses
                WHERE id = %s::uuid AND user_id = %s::uuid
                RETURNING id
                """,
                (expense_id, user_id),
            )
            conn.commit()
            result = cursor.fetchone()

            if result:
                return f"Deleted expense {expense_id}"
            else:
                return f"Expense {expense_id} not found or unauthorized"

        else:
            return f"Error: Unknown action '{action}'"

    except Exception as e:
        return f"Database error: {str(e)}"

    finally:
        if "cursor" in locals():
            cursor.close()
        if "conn" in locals():
            conn.close()
