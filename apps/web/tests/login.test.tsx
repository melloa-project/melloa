import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { LoginPage } from "../src/pages/login";

describe("LoginPage", () => {
  it("states the private and independent authority boundaries", () => {
    render(<MemoryRouter><LoginPage login={vi.fn()} status={null} /></MemoryRouter>);

    expect(screen.getByText("Private by design")).toBeInTheDocument();
    expect(screen.getByText("Guardian remains independent")).toBeInTheDocument();
    expect(screen.getByText("No browser persistence")).toBeInTheDocument();
  });

  it("submits the owner credential and clears the field", async () => {
    const login = vi.fn(async () => undefined);
    render(<MemoryRouter><LoginPage login={login} status={null} /></MemoryRouter>);
    const input = screen.getByLabelText("Owner credential");
    fireEvent.change(input, { target: { value: "a".repeat(32) } });
    fireEvent.click(screen.getByRole("button", { name: /Open Owner Console/ }));

    await waitFor(() => expect(login).toHaveBeenCalledWith("a".repeat(32)));
    expect(input).toHaveValue("");
  });
});
