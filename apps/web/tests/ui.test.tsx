import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "../src/components/ui";

function ModalHarness({ onClose = vi.fn() }: { readonly onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} type="button">Explain answer</button>
      <Modal
        description="Context and privacy facts for this answer."
        onClose={() => {
          onClose();
          setOpen(false);
        }}
        open={open}
        title="Why this answer?"
      >
        <button type="button">Read final detail</button>
      </Modal>
    </>
  );
}

describe("Modal", () => {
  it("exposes its description, closes on Escape, and restores trigger focus", async () => {
    const onClose = vi.fn();
    render(<ModalHarness onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "Explain answer" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Why this answer?" });
    expect(dialog).toHaveAccessibleDescription("Context and privacy facts for this answer.");
    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onClose).toHaveBeenCalledOnce();
    expect(trigger).toHaveFocus();
  });

  it("wraps keyboard focus within the open dialog", () => {
    render(<ModalHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Explain answer" }));
    const close = screen.getByRole("button", { name: "Close dialog" });
    const finalControl = screen.getByRole("button", { name: "Read final detail" });

    finalControl.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(finalControl).toHaveFocus();
  });
});
